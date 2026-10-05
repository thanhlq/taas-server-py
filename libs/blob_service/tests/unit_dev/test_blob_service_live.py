"""blob_service against local RustFS + Postgres: tenant provisioning, sys_settings.bucket, behaviour suite.

Throwaway `taas_tenants` rows and `e2e-py-…` buckets are deleted at teardown.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field

import httpx
import pytest
from blob_service import DefaultBlobService, create_blob_service
from foundation.blob import (
    BlobAdapterT,
    BlobConflictError,
    BlobPresignOptions,
    BlobSettings,
    BlobTenantNotFoundError,
)
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobHttpResponse,
    BlobSuiteContext,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PREFIX = 'e2e-py-'


class HttpxBlobClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> BlobHttpResponse:
        response = await self._client.request(
            method, httpx.URL(url), headers=dict(headers or {}), content=content
        )
        return BlobHttpResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
        )


async def _drop_bucket(adapter: BlobAdapterT, bucket: str) -> None:
    if not await adapter.bucket_exists(bucket):
        return
    while (page := await adapter.list(bucket)).items:
        await adapter.delete_many(bucket, [item.key for item in page.items])
    await adapter.delete_bucket(bucket)


@dataclass
class Live:
    engine: AsyncEngine
    service: DefaultBlobService
    make_service: Callable[[], DefaultBlobService]
    tenant_ids: list[uuid.UUID] = field(default_factory=list[uuid.UUID])
    buckets: set[str] = field(default_factory=set[str])

    async def insert_tenant(
        self, sys_settings: dict[str, object] | None = None
    ) -> tuple[uuid.UUID, str]:
        tenant_id = uuid.uuid4()
        async with self.engine.begin() as conn:
            while True:
                code = f'{random.randint(0, 99_999_999):08d}'
                taken = await conn.execute(
                    text('SELECT 1 FROM taas_tenants WHERE tenant_code = :c'),
                    {'c': code},
                )
                if taken.first() is None:
                    break
            await conn.execute(
                text(
                    'INSERT INTO taas_tenants (id, name, slug, status, tenant_code, account_type, sys_settings, '
                    "created_at, updated_at) VALUES (:id, :name, :slug, 'ACTIVE', :code, 'organization', "
                    'CAST(:sys AS jsonb), now(), now())'
                ),
                {
                    'id': tenant_id,
                    'name': f'blob e2e {code}',
                    'slug': f'blob-e2e-{tenant_id.hex[:12]}',
                    'code': code,
                    'sys': json.dumps(sys_settings or {}),
                },
            )
        self.tenant_ids.append(tenant_id)
        self.buckets.add(f'{PREFIX}{code}')
        return tenant_id, code

    async def stored_bucket(self, tenant_id: uuid.UUID) -> str | None:
        async with self.engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT sys_settings ->> 'bucket' FROM taas_tenants WHERE id = :id"
                ),
                {'id': tenant_id},
            )
            return row.scalar_one_or_none()


@pytest.fixture
async def live(
    engine: AsyncEngine, rustfs_endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Live]:
    # The factory builds the S3 adapter from the environment, as in production.
    monkeypatch.setenv('AWS_ENDPOINT_URL', rustfs_endpoint)
    monkeypatch.setenv('AWS_REGION', 'us-east-1')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'app')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'app')
    monkeypatch.delenv('AWS_S3_FORCE_PATH_STYLE', raising=False)
    settings = BlobSettings(
        BLOB_STORAGE_PROVIDER='s3', BLOB_BUCKET_PREFIX=PREFIX, BLOB_PRESIGN_EXPIRES=300
    )
    services: list[DefaultBlobService] = []

    def make_service() -> DefaultBlobService:
        service = create_blob_service(settings, engine=engine, register=False)
        assert isinstance(service, DefaultBlobService)
        services.append(service)
        return service

    state = Live(engine=engine, service=make_service(), make_service=make_service)
    try:
        yield state
    finally:
        adapter = state.service.adapter
        for bucket in state.buckets:
            await _drop_bucket(adapter, bucket)
        if state.tenant_ids:
            async with engine.begin() as conn:
                await conn.execute(
                    text('DELETE FROM taas_tenants WHERE id = ANY(:ids)'),
                    {'ids': state.tenant_ids},
                )
        for service in services:
            await service.aclose()


async def test_provisions_tenant_bucket(live: Live) -> None:
    tenant_id, code = await live.insert_tenant()
    assert await live.stored_bucket(tenant_id) is None

    store = await live.service.for_tenant(tenant_id)
    assert store.bucket == f'{PREFIX}{code}'
    assert await live.stored_bucket(tenant_id) == store.bucket
    assert await live.service.adapter.bucket_exists(store.bucket)

    await store.put('projects/p1/readme.txt', 'hello tenant', None)
    url = await store.presign(
        'projects/p1/readme.txt', BlobPresignOptions(download_name='readme.txt')
    )
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(httpx.URL(url))
    assert response.status_code == 200
    assert response.content == b'hello tenant'

    # A fresh process (empty cache) reads sys_settings.bucket; a renamed prefix never moves the tenant.
    other = live.make_service()
    other._bucket_prefix = 'e2e-py-renamed-'  # pyright: ignore[reportPrivateUsage]
    assert await other.bucket_for(str(tenant_id)) == store.bucket


async def test_concurrent_first_calls_agree(live: Live) -> None:
    tenant_id, code = await live.insert_tenant()
    services = [live.make_service() for _ in range(3)]  # three "processes"
    results = await asyncio.gather(
        *(s.bucket_for(tenant_id) for s in services for _ in range(4))
    )
    assert set(results) == {f'{PREFIX}{code}'}
    assert await live.stored_bucket(tenant_id) == f'{PREFIX}{code}'


async def test_existing_bucket_is_kept(live: Live) -> None:
    custom = f'{PREFIX}custom-{uuid.uuid4().hex[:8]}'
    tenant_id, code = await live.insert_tenant({'bucket': custom})
    live.buckets.add(custom)
    assert await live.service.bucket_for(tenant_id) == custom
    assert not await live.service.adapter.bucket_exists(f'{PREFIX}{code}')


async def test_unknown_tenant(live: Live) -> None:
    with pytest.raises(BlobTenantNotFoundError):
        await live.service.for_tenant(uuid.uuid4())
    with pytest.raises(BlobTenantNotFoundError):
        await live.service.for_tenant('not-a-uuid')


@pytest.mark.parametrize('stored', [42, None, '', {'name': 'x'}])
async def test_non_string_stored_bucket_is_a_conflict(
    live: Live, stored: object
) -> None:
    tenant_id, _code = await live.insert_tenant({'bucket': stored})
    with pytest.raises(BlobConflictError):
        await live.service.bucket_for(tenant_id)


@pytest.mark.parametrize('check', sorted(BLOB_ADAPTER_CHECKS))
async def test_behaviour_on_tenant_bucket(check: str, live: Live) -> None:
    tenant_id, _code = await live.insert_tenant()
    bucket = await live.service.bucket_for(tenant_id)

    def new_name() -> str:
        name = f'{PREFIX}{uuid.uuid4().hex[:16]}'
        live.buckets.add(name)
        return name

    async with httpx.AsyncClient(timeout=10) as http:
        ctx = BlobSuiteContext(
            adapter=live.service.adapter,
            bucket=bucket,
            new_bucket_name=new_name,
            http=HttpxBlobClient(http),
        )
        try:
            await BLOB_ADAPTER_CHECKS[check](ctx)
        except BlobCheckSkipped as e:
            pytest.skip(str(e))
