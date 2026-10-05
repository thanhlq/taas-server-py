"""Local RustFS helpers for the unit_dev layer (docker-compose.infra.yml `storage`: localhost:19000, app / app)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping

import httpx
from blob_s3 import S3BlobAdapter, S3BlobSettings
from foundation.blob.conformance import BlobHttpResponse

RUSTFS_ENDPOINT = os.getenv('BLOB_TEST_RUSTFS_ENDPOINT', 'http://localhost:19000')
LIVE_BUCKET_PREFIX = 'e2e-py-'


def rustfs_reachable() -> bool:
    try:
        return httpx.get(f'{RUSTFS_ENDPOINT}/health', timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


def rustfs_settings() -> S3BlobSettings:
    return S3BlobSettings(
        AWS_ENDPOINT_URL=RUSTFS_ENDPOINT,
        AWS_REGION='us-east-1',
        AWS_ACCESS_KEY_ID='app',
        AWS_SECRET_ACCESS_KEY='app',
        AWS_S3_FORCE_PATH_STYLE=True,
    )


def rustfs_adapter() -> S3BlobAdapter:
    return S3BlobAdapter(rustfs_settings(), presign_expires=900)


def new_live_bucket_name() -> str:
    return f'{LIVE_BUCKET_PREFIX}{uuid.uuid4().hex[:16]}'


async def drop_bucket(adapter: S3BlobAdapter, bucket: str) -> None:
    """Empty and delete a bucket (ignores a missing one)."""
    if not await adapter.bucket_exists(bucket):
        return
    while True:
        page = await adapter.list(bucket)
        if not page.items:
            break
        await adapter.delete_many(bucket, [item.key for item in page.items])
    await adapter.delete_bucket(bucket)


class HttpxBlobClient:
    """`BlobHttpClient` over httpx, without credentials."""

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
        # The presigned URL is already encoded: send it verbatim.
        response = await self._client.request(
            method, httpx.URL(url), headers=dict(headers or {}), content=content
        )
        return BlobHttpResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
        )
