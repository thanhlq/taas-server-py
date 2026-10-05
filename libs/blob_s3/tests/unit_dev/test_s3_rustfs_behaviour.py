"""The shared behaviour suite against local RustFS (skipped when localhost:19000 is unreachable).

Every bucket is named `e2e-py-…` and deleted at teardown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from foundation.blob import BlobInfo
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobSuiteContext,
)
from rustfs_support import (
    HttpxBlobClient,
    drop_bucket,
    new_live_bucket_name,
    rustfs_adapter,
    rustfs_reachable,
)

pytestmark = pytest.mark.skipif(
    not rustfs_reachable(), reason='RustFS not reachable on localhost:19000'
)


@pytest.fixture
async def live_ctx() -> AsyncIterator[BlobSuiteContext]:
    adapter = rustfs_adapter()
    names: list[str] = []

    def new_name() -> str:
        names.append(new_live_bucket_name())
        return names[-1]

    bucket = new_name()
    await adapter.ensure_bucket(bucket)
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            yield BlobSuiteContext(
                adapter=adapter,
                bucket=bucket,
                new_bucket_name=new_name,
                http=HttpxBlobClient(http),
            )
        finally:
            for name in names:
                await drop_bucket(adapter, name)
            await adapter.aclose()


@pytest.mark.parametrize('check', sorted(BLOB_ADAPTER_CHECKS))
async def test_behaviour_on_rustfs(check: str, live_ctx: BlobSuiteContext) -> None:
    try:
        await BLOB_ADAPTER_CHECKS[check](live_ctx)
    except BlobCheckSkipped as e:
        pytest.skip(str(e))


async def test_list_items_and_large_delete_many(live_ctx: BlobSuiteContext) -> None:
    adapter, bucket = live_ctx.adapter, live_ctx.bucket
    info: BlobInfo = await adapter.put(bucket, 'big/0.txt', b'abc')
    page = await adapter.list(bucket, None)
    assert [i.key for i in page.items] == ['big/0.txt']
    assert page.items[0].etag == info.etag
    assert page.items[0].last_modified is not None
    # 1005 keys (mostly missing) → two DeleteObjects batches
    await adapter.delete_many(bucket, [f'big/{i}.txt' for i in range(1005)])
    assert (await adapter.list(bucket)).items == []


async def test_presigned_put_wrong_content_type_rejected(
    live_ctx: BlobSuiteContext,
) -> None:
    from foundation.blob import BlobPresignOptions

    assert live_ctx.http is not None
    url = await live_ctx.adapter.presign(
        live_ctx.bucket,
        'ct.txt',
        BlobPresignOptions(method='PUT', content_type='text/plain'),
    )
    response = await live_ctx.http(
        'PUT', url, headers={'content-type': 'image/png'}, content=b'x'
    )
    assert response.status == 403
