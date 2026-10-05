"""The shared behaviour suite (foundation.blob.conformance) on MemoryBlobAdapter."""

from __future__ import annotations

import itertools

import pytest
from blob_service import MemoryBlobAdapter
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobSuiteContext,
)

_counter = itertools.count()


@pytest.fixture
async def ctx() -> BlobSuiteContext:
    adapter = MemoryBlobAdapter(presign_expires=900)
    await adapter.ensure_bucket('suite-bucket')
    return BlobSuiteContext(
        adapter=adapter,
        bucket='suite-bucket',
        new_bucket_name=lambda: f'suite-new-{next(_counter)}',
    )


@pytest.mark.parametrize('check', sorted(BLOB_ADAPTER_CHECKS))
async def test_behaviour(check: str, ctx: BlobSuiteContext) -> None:
    try:
        await BLOB_ADAPTER_CHECKS[check](ctx)
    except BlobCheckSkipped as e:
        pytest.skip(str(e))


async def test_presign_url_shape() -> None:
    adapter = MemoryBlobAdapter(presign_expires=120)
    from foundation.blob import BlobPresignOptions

    assert adapter.provider == 'memory'
    url = await adapter.presign('bucket-a', 'dir/a b.txt')
    assert url == 'memory://bucket-a/dir/a%20b.txt?method=GET&expires_in=120'
    url = await adapter.presign(
        'bucket-a', 'k', BlobPresignOptions(method='PUT', content_type='text/plain')
    )
    assert 'method=PUT' in url and 'content_type=text%2Fplain' in url


async def test_missing_bucket() -> None:
    from foundation.blob import BlobNotFoundError

    adapter = MemoryBlobAdapter()
    assert await adapter.head('no-such-bucket', 'k') is None
    assert await adapter.exists('no-such-bucket', 'k') is False
    with pytest.raises(BlobNotFoundError):
        await adapter.put('no-such-bucket', 'k', b'x')
    with pytest.raises(BlobNotFoundError):
        await adapter.get('no-such-bucket', 'k')
