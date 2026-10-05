"""AzureBlobAdapter with a faked azure-storage-blob aio client (no network) and real SAS signing (offline)."""

from __future__ import annotations

import base64
import itertools
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.exceptions import HttpResponseError
from azure_fakes import FakeBlobServiceClient
from blob_azure import DELETE_BATCH_SIZE, AzureBlobAdapter, AzureBlobSettings
from foundation.blob import BlobNotFoundError, BlobPresignOptions, BlobProviderError
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobSuiteContext,
)

_counter = itertools.count()
ACCOUNT_KEY = base64.b64encode(b'0' * 64).decode()
CONNECTION_STRING = f'DefaultEndpointsProtocol=https;AccountName=acct;AccountKey={ACCOUNT_KEY};EndpointSuffix=core.windows.net'


def _settings(**overrides: str) -> AzureBlobSettings:
    values = {
        'BLOB_AZURE_CONNECTION_STRING': CONNECTION_STRING,
        'BLOB_AZURE_ACCOUNT_NAME': '',
        'BLOB_AZURE_ACCOUNT_KEY': '',
    }
    values.update(overrides)
    return AzureBlobSettings(**values)


@pytest.fixture
async def ctx() -> BlobSuiteContext:
    adapter = AzureBlobAdapter(
        _settings(), client=FakeBlobServiceClient(), presign_expires=900
    )
    await adapter.ensure_bucket('suite-bucket')
    return BlobSuiteContext(
        adapter=adapter,
        bucket='suite-bucket',
        new_bucket_name=lambda: f'suite-new-{next(_counter)}',
    )


@pytest.mark.parametrize('check', sorted(BLOB_ADAPTER_CHECKS))
async def test_behaviour_with_fake_client(check: str, ctx: BlobSuiteContext) -> None:
    try:
        await BLOB_ADAPTER_CHECKS[check](ctx)
    except BlobCheckSkipped as e:
        pytest.skip(str(e))


def test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        'BLOB_AZURE_CONNECTION_STRING',
        'BLOB_AZURE_ACCOUNT_NAME',
        'BLOB_AZURE_ACCOUNT_KEY',
    ):
        monkeypatch.delenv(key, raising=False)
    empty = AzureBlobSettings()
    assert (empty.account_name, empty.account_key) == (None, None)
    from_cs = _settings()
    assert (from_cs.account_name, from_cs.account_key) == ('acct', ACCOUNT_KEY)
    explicit = _settings(
        BLOB_AZURE_CONNECTION_STRING='',
        BLOB_AZURE_ACCOUNT_NAME='other',
        BLOB_AZURE_ACCOUNT_KEY='k',
    )
    assert (explicit.account_name, explicit.account_key) == ('other', 'k')


async def test_ensure_bucket_private_and_idempotent() -> None:
    client = FakeBlobServiceClient()
    adapter = AzureBlobAdapter(_settings(), client=client)
    assert adapter.provider == 'azure'
    await adapter.ensure_bucket('bucket-a')
    await adapter.ensure_bucket('bucket-a')
    assert client.created == [('bucket-a', {})]  # no public_access argument → private


async def test_copy_waits_for_pending() -> None:
    client = FakeBlobServiceClient(copy_pending=True)
    adapter = AzureBlobAdapter(_settings(), client=client)
    await adapter.ensure_bucket('bucket-a')
    await adapter.put('bucket-a', 'src.txt', b'x')
    await adapter.copy('bucket-a', 'src.txt', 'dst.txt')
    assert client.store['bucket-a']['dst.txt'].copy_status == 'success'


async def test_delete_many_batches_of_256() -> None:
    client = FakeBlobServiceClient()
    adapter = AzureBlobAdapter(_settings(), client=client)
    await adapter.ensure_bucket('bucket-a')
    await adapter.delete_many('bucket-a', [f'k{i}' for i in range(600)])
    assert client.delete_batches == [DELETE_BATCH_SIZE, DELETE_BATCH_SIZE, 88]


async def test_presign_sas_offline() -> None:
    adapter = AzureBlobAdapter(
        _settings(), client=FakeBlobServiceClient(), presign_expires=900
    )
    url = await adapter.presign(
        'bucket-a', 'dir/a b.txt', BlobPresignOptions(download_name='r.pdf')
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == 'acct.blob.core.windows.net'
    assert parts.path == '/bucket-a/dir/a%20b.txt'
    assert query['sp'] == ['r']
    assert query['sr'] == ['b']
    assert query['rscd'] == ['attachment; filename="r.pdf"']
    assert query['sig']
    put = parse_qs(
        urlsplit(
            await adapter.presign('bucket-a', 'k', BlobPresignOptions(method='PUT'))
        ).query
    )
    assert put['sp'] == ['cw']


async def test_presign_with_real_client_from_connection_string() -> None:
    adapter = AzureBlobAdapter(_settings())
    try:
        url = await adapter.presign('bucket-a', 'k.txt')
    finally:
        await adapter.aclose()
    assert url.startswith('https://acct.blob.core.windows.net/bucket-a/k.txt?')


async def test_presign_needs_account_key() -> None:
    settings = _settings(
        BLOB_AZURE_CONNECTION_STRING='', BLOB_AZURE_ACCOUNT_NAME='acct'
    )
    adapter = AzureBlobAdapter(settings, client=FakeBlobServiceClient())
    with pytest.raises(BlobProviderError, match='account key|ACCOUNT_KEY'):
        await adapter.presign('bucket-a', 'k')


async def test_error_mapping() -> None:
    client = FakeBlobServiceClient()
    adapter = AzureBlobAdapter(_settings(), client=client)
    with pytest.raises(BlobNotFoundError):
        await adapter.put('missing-bucket', 'k', b'x')
    with pytest.raises(BlobNotFoundError):
        await adapter.get('missing-bucket', 'k')
    assert await adapter.head('missing-bucket', 'k') is None

    async def boom(**_kw: object) -> None:
        raise HttpResponseError(message='server busy')

    await adapter.ensure_bucket('bucket-a')
    blob = client.get_blob_client('bucket-a', 'k')
    blob_cls = type(blob)
    original = blob_cls.upload_blob
    blob_cls.upload_blob = lambda self, *a, **kw: boom()  # type: ignore[method-assign,assignment]
    try:
        with pytest.raises(BlobProviderError, match='azure put failed'):
            await adapter.put('bucket-a', 'k', b'x')
    finally:
        blob_cls.upload_blob = original  # type: ignore[method-assign]


async def test_missing_configuration() -> None:
    adapter = AzureBlobAdapter(_settings(BLOB_AZURE_CONNECTION_STRING=''))
    with pytest.raises(BlobProviderError, match='BLOB_AZURE_CONNECTION_STRING'):
        await adapter.bucket_exists('bucket-a')


async def test_injected_client_not_closed() -> None:
    client = FakeBlobServiceClient()
    await AzureBlobAdapter(_settings(), client=client).aclose()
    assert not client.closed
