"""DefaultBlobService: tenant bucket resolution, provisioning, cache, concurrency, factory."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from blob_service import (
    BoundTenantBlobStore,
    DefaultBlobService,
    MemoryBlobAdapter,
    MemoryTenantBucketRegistry,
    create_blob_adapter,
    create_blob_service,
    parse_tenant_uuid,
)
from foundation.blob import (
    BlobListOptions,
    BlobServiceT,
    BlobSettings,
    BlobTenantNotFoundError,
    BlobValidationError,
    TenantBucketRecord,
    TenantBucketRegistryT,
    TenantId,
)
from foundation.state import get_service


class CountingRegistry(TenantBucketRegistryT):
    """Wraps the memory registry, counts calls and yields control to provoke races."""

    def __init__(self, inner: MemoryTenantBucketRegistry) -> None:
        self.inner = inner
        self.gets = 0
        self.sets = 0

    async def get(self, tenant_id: TenantId) -> TenantBucketRecord | None:
        self.gets += 1
        await asyncio.sleep(0)
        return await self.inner.get(tenant_id)

    async def set_if_absent(self, tenant_id: TenantId, bucket: str) -> str:
        self.sets += 1
        await asyncio.sleep(0)
        return await self.inner.set_if_absent(tenant_id, bucket)


TENANT = str(uuid.uuid4())


@pytest.fixture
def registry() -> MemoryTenantBucketRegistry:
    return MemoryTenantBucketRegistry({TENANT: '12345678'})


async def test_provisions_bucket_and_stores_it(
    registry: MemoryTenantBucketRegistry,
) -> None:
    adapter = MemoryBlobAdapter()
    service = DefaultBlobService(adapter, registry, bucket_prefix='taas-')
    store = await service.for_tenant(TENANT)
    assert isinstance(store, BoundTenantBlobStore)
    assert store.bucket == 'taas-12345678'
    assert store.tenant_id == TENANT
    assert await adapter.bucket_exists('taas-12345678')
    record = await registry.get(TENANT)
    assert record == TenantBucketRecord(tenant_code='12345678', bucket='taas-12345678')
    assert await service.bucket_for(TENANT) == 'taas-12345678'


async def test_tenant_store_delegates(registry: MemoryTenantBucketRegistry) -> None:
    service = DefaultBlobService(MemoryBlobAdapter(), registry, bucket_prefix='taas-')
    store = await service.for_tenant(TENANT)
    info = await store.put('projects/p1/a.txt', 'hello')
    assert info.bucket == 'taas-12345678'
    assert (await store.get('projects/p1/a.txt')).body == b'hello'  # type: ignore[union-attr]
    assert (await store.head('projects/p1/a.txt')).size == 5  # type: ignore[union-attr]
    assert await store.exists('projects/p1/a.txt')
    await store.copy('projects/p1/a.txt', 'projects/p1/b.txt')
    page = await store.list(BlobListOptions(prefix='projects/'))
    assert [i.key for i in page.items] == ['projects/p1/a.txt', 'projects/p1/b.txt']
    assert (await store.presign('projects/p1/a.txt')).startswith(
        'memory://taas-12345678/'
    )
    await store.delete('projects/p1/a.txt')
    await store.delete_many(['projects/p1/b.txt'])
    assert (await store.list()).items == []


async def test_existing_bucket_is_source_of_truth(
    registry: MemoryTenantBucketRegistry,
) -> None:
    registry.add_tenant(TENANT, '12345678', bucket='legacy-12345678')
    adapter = MemoryBlobAdapter()
    service = DefaultBlobService(adapter, registry, bucket_prefix='new-prefix-')
    assert await service.bucket_for(TENANT) == 'legacy-12345678'
    assert not await adapter.bucket_exists(
        'new-prefix-12345678'
    )  # no provisioning, no move


async def test_unknown_tenant(registry: MemoryTenantBucketRegistry) -> None:
    service = DefaultBlobService(MemoryBlobAdapter(), registry, bucket_prefix='taas-')
    with pytest.raises(BlobTenantNotFoundError) as exc:
        await service.for_tenant(uuid.uuid4())
    assert exc.value.code == 'blob_tenant_not_found'


async def test_invalid_tenant_code_gives_validation_error(
    registry: MemoryTenantBucketRegistry,
) -> None:
    registry.add_tenant(TENANT, 'NOT_VALID')
    service = DefaultBlobService(MemoryBlobAdapter(), registry, bucket_prefix='taas-')
    with pytest.raises(BlobValidationError):
        await service.bucket_for(TENANT)


async def test_cache_per_process(registry: MemoryTenantBucketRegistry) -> None:
    counting = CountingRegistry(registry)
    service = DefaultBlobService(MemoryBlobAdapter(), counting, bucket_prefix='taas-')
    for _ in range(3):
        await service.bucket_for(TENANT)
    await service.bucket_for(uuid.UUID(TENANT))  # same tenant, UUID form
    assert counting.gets == 1
    assert counting.sets == 1
    service.clear_cache()
    await service.bucket_for(TENANT)
    assert counting.gets == 2
    assert counting.sets == 1  # already stored


async def test_concurrent_first_calls_agree(
    registry: MemoryTenantBucketRegistry,
) -> None:
    counting = CountingRegistry(registry)
    service = DefaultBlobService(MemoryBlobAdapter(), counting, bucket_prefix='taas-')
    results = await asyncio.gather(*(service.bucket_for(TENANT) for _ in range(20)))
    assert set(results) == {'taas-12345678'}
    assert counting.sets == 1  # deduplicated in process


async def test_concurrent_services_agree_via_registry(
    registry: MemoryTenantBucketRegistry,
) -> None:
    """Two processes (services) with different prefixes race: both end up with the first stored name."""
    adapter = MemoryBlobAdapter()
    first = DefaultBlobService(
        adapter, CountingRegistry(registry), bucket_prefix='aaa-'
    )
    second = DefaultBlobService(
        adapter, CountingRegistry(registry), bucket_prefix='bbb-'
    )
    a, b = await asyncio.gather(first.bucket_for(TENANT), second.bucket_for(TENANT))
    assert a == b
    assert (await registry.get(TENANT)).bucket == a  # type: ignore[union-attr]


async def test_memory_registry_set_if_absent() -> None:
    registry = MemoryTenantBucketRegistry()
    registry.add_tenant('t1', '00000001')
    assert await registry.set_if_absent('t1', 'b-one') == 'b-one'
    assert await registry.set_if_absent('t1', 'b-two') == 'b-one'
    with pytest.raises(BlobTenantNotFoundError):
        await registry.set_if_absent('missing', 'x')
    registry.remove_tenant('t1')
    assert await registry.get('t1') is None


def test_parse_tenant_uuid() -> None:
    value = uuid.uuid4()
    assert parse_tenant_uuid(value) is value
    assert parse_tenant_uuid(str(value)) == value
    assert parse_tenant_uuid('not-a-uuid') is None


@pytest.mark.parametrize('tenant_id', ['', '   '])
async def test_empty_tenant_id_is_invalid(
    registry: MemoryTenantBucketRegistry, tenant_id: str
) -> None:
    service = DefaultBlobService(MemoryBlobAdapter(), registry, bucket_prefix='taas-')
    with pytest.raises(BlobValidationError):
        await service.for_tenant(tenant_id)


async def test_non_uuid_tenant_is_not_found_with_sql_registry() -> None:
    from blob_service import SqlTenantBucketRegistry
    from sqlalchemy.ext.asyncio import create_async_engine

    # never connects: a malformed id cannot exist
    engine = create_async_engine('postgresql+psycopg_async://u:p@localhost:1/none')
    service = DefaultBlobService(
        MemoryBlobAdapter(), SqlTenantBucketRegistry(engine), bucket_prefix='taas-'
    )
    with pytest.raises(BlobTenantNotFoundError):
        await service.bucket_for('not-a-uuid')
    with pytest.raises(BlobTenantNotFoundError):
        await SqlTenantBucketRegistry(engine).set_if_absent('not-a-uuid', 'taas-1')


async def test_tenant_store_presign_uses_service_default(
    registry: MemoryTenantBucketRegistry,
) -> None:
    from foundation.blob import BlobPresignOptions

    adapter = MemoryBlobAdapter()
    service = DefaultBlobService(
        adapter, registry, bucket_prefix='taas-', presign_expires=120
    )
    assert service.presign_expires == 120
    store = await service.for_tenant(TENANT)
    assert 'expires_in=120' in await store.presign('a.txt')
    assert 'expires_in=5' in await store.presign(
        'a.txt', BlobPresignOptions(expires_in=5)
    )
    assert 'expires_in=900' in await adapter.presign(
        store.bucket, 'a.txt'
    )  # adapter default
    with pytest.raises(BlobValidationError):
        DefaultBlobService(adapter, registry, presign_expires=0)


async def test_factory_registers_service(registry: MemoryTenantBucketRegistry) -> None:
    settings = BlobSettings(
        BLOB_STORAGE_PROVIDER='memory',
        BLOB_BUCKET_PREFIX='unit-',
        BLOB_PRESIGN_EXPIRES=30,
    )
    service = create_blob_service(settings, registry=registry)
    assert get_service(BlobServiceT) is service
    assert service.adapter.provider == 'memory'
    assert await service.bucket_for(TENANT) == 'unit-12345678'
    url = await (await service.for_tenant(TENANT)).presign('a.txt')
    assert 'expires_in=30' in url
    await service.aclose()


def test_factory_requires_registry_or_engine() -> None:
    with pytest.raises(BlobValidationError):
        create_blob_service(
            BlobSettings(BLOB_STORAGE_PROVIDER='memory'), register=False
        )


def test_factory_with_engine_uses_sql_registry() -> None:
    from blob_service import SqlTenantBucketRegistry
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine('postgresql+psycopg_async://u:p@localhost:1/none')
    service = create_blob_service(
        BlobSettings(BLOB_STORAGE_PROVIDER='memory'), engine=engine, register=False
    )
    assert isinstance(service, DefaultBlobService)
    assert isinstance(service._registry, SqlTenantBucketRegistry)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ('provider', 'class_name'),
    [
        ('s3', 'S3BlobAdapter'),
        ('gcp', 'GcpBlobAdapter'),
        ('gcs', 'GcpBlobAdapter'),
        ('azure', 'AzureBlobAdapter'),
        ('memory', 'MemoryBlobAdapter'),
    ],
)
def test_create_blob_adapter_by_provider(provider: str, class_name: str) -> None:
    adapter = create_blob_adapter(
        BlobSettings(BLOB_STORAGE_PROVIDER=provider, BLOB_PRESIGN_EXPIRES=42)
    )
    # adapters keep the 900 s default; BLOB_PRESIGN_EXPIRES applies through tenant stores
    assert type(adapter).__name__ == class_name
    assert adapter._presign_expires == 900  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
