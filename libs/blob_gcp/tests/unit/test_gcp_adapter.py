"""GcpBlobAdapter with a faked google-cloud-storage client (no network)."""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from blob_gcp import DELETE_BATCH_SIZE, GcpBlobAdapter, GcpBlobSettings
from foundation.blob import (
    BlobConflictError,
    BlobNotFoundError,
    BlobPresignOptions,
    BlobProviderError,
)
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobSuiteContext,
)
from gcs_fakes import FakeGcsClient
from google.api_core import exceptions as gexc

_counter = itertools.count()


def _adapter(client: FakeGcsClient, **kw: object) -> GcpBlobAdapter:
    settings = GcpBlobSettings(BLOB_GCP_PROJECT_ID='proj', BLOB_GCP_LOCATION='EU')
    return GcpBlobAdapter(settings, client=client, presign_expires=900, **kw)  # type: ignore[arg-type]


@pytest.fixture
async def ctx() -> BlobSuiteContext:
    adapter = _adapter(FakeGcsClient())
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
    for key in ('BLOB_GCP_PROJECT_ID', 'BLOB_GCP_LOCATION', 'GOOGLE_CLOUD_PROJECT'):
        monkeypatch.delenv(key, raising=False)
    settings = GcpBlobSettings()
    assert settings.BLOB_GCP_LOCATION == 'EU'
    assert settings.project_id is None
    monkeypatch.setenv('BLOB_GCP_PROJECT_ID', 'my-proj')
    monkeypatch.setenv('BLOB_GCP_LOCATION', 'europe-west1')
    settings = GcpBlobSettings()
    assert (settings.project_id, settings.BLOB_GCP_LOCATION) == (
        'my-proj',
        'europe-west1',
    )


async def test_ensure_bucket_is_private_and_located() -> None:
    client = FakeGcsClient(foreign_buckets={'someone-elses'})
    adapter = _adapter(client)
    assert adapter.provider == 'gcp'
    await adapter.ensure_bucket('bucket-a')
    await adapter.ensure_bucket('bucket-a')  # Conflict + readable → ours
    name, location, iam = client.created[0]
    assert (name, location) == ('bucket-a', 'EU')
    assert iam.uniform_bucket_level_access_enabled is True
    assert iam.public_access_prevention == 'enforced'
    with pytest.raises(BlobConflictError):
        await adapter.ensure_bucket('someone-elses')


async def test_presign_kwargs() -> None:
    client = FakeGcsClient()
    adapter = _adapter(client)
    await adapter.presign(
        'bucket-a', 'k.txt', BlobPresignOptions(download_name='r.pdf')
    )
    await adapter.presign(
        'bucket-a',
        'k.txt',
        BlobPresignOptions(method='PUT', content_type='text/plain', expires_in=60),
    )
    get_kwargs, put_kwargs = client.signed
    assert get_kwargs == {
        'version': 'v4',
        'expiration': timedelta(seconds=900),
        'method': 'GET',
        'response_disposition': 'attachment; filename="r.pdf"',
    }
    assert put_kwargs == {
        'version': 'v4',
        'expiration': timedelta(seconds=60),
        'method': 'PUT',
        'content_type': 'text/plain',
    }


async def test_delete_many_batches() -> None:
    client = FakeGcsClient()
    adapter = _adapter(client)
    await adapter.ensure_bucket('bucket-a')
    await adapter.delete_many('bucket-a', [f'k{i}' for i in range(2001)])
    assert client.delete_batches == [DELETE_BATCH_SIZE, DELETE_BATCH_SIZE, 1]


async def test_error_mapping() -> None:
    client = FakeGcsClient()
    adapter = _adapter(client)
    with pytest.raises(BlobNotFoundError):
        await adapter.put('missing-bucket', 'k', b'x')
    with pytest.raises(BlobNotFoundError):
        await adapter.get('missing-bucket', 'k')
    assert await adapter.head('missing-bucket', 'k') is None

    def boom(*_a: object, **_kw: object) -> None:
        raise gexc.InternalServerError('boom')

    client.get_bucket = boom  # type: ignore[method-assign]
    client.create_bucket = boom  # type: ignore[method-assign]
    with pytest.raises(BlobProviderError, match='gcp ensure_bucket failed'):
        await adapter.ensure_bucket('bucket-b')


async def test_aclose_leaves_injected_client_open() -> None:
    client = FakeGcsClient()
    adapter = _adapter(client)
    await adapter.aclose()
    assert not client.closed


def _service_account_client() -> object:
    """A real storage.Client with a throwaway service-account key: V4 signing works offline."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.cloud import storage
    from google.oauth2 import service_account

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    credentials = service_account.Credentials.from_service_account_info(
        {
            'type': 'service_account',
            'client_email': 'blob-test@proj.iam.gserviceaccount.com',
            'private_key': pem,
            'private_key_id': 'test',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'project_id': 'proj',
        }
    )
    return storage.Client(project='proj', credentials=credentials)


async def test_presign_with_real_sdk_offline() -> None:
    from urllib.parse import parse_qs, urlsplit

    adapter = _adapter(_service_account_client())  # type: ignore[arg-type]
    url = await adapter.presign(
        'bucket-a', 'dir/a b.txt', BlobPresignOptions(download_name='r.pdf')
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == 'storage.googleapis.com'
    assert parts.path == '/bucket-a/dir/a%20b.txt'
    assert query['X-Goog-Algorithm'] == ['GOOG4-RSA-SHA256']
    assert query['X-Goog-Expires'] == ['900']
    assert query['response-content-disposition'] == ['attachment; filename="r.pdf"']
    put_url = await adapter.presign(
        'bucket-a',
        'k.txt',
        BlobPresignOptions(method='PUT', content_type='text/plain', expires_in=60),
    )
    put_query = parse_qs(urlsplit(put_url).query)
    assert put_query['X-Goog-Expires'] == ['60']
    assert 'content-type' in put_query['X-Goog-SignedHeaders'][0]
