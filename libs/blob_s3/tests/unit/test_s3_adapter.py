"""S3BlobAdapter with a fake client (behaviour suite + S3 specifics) and real presigning (no network)."""

from __future__ import annotations

import itertools
from urllib.parse import parse_qs, urlsplit

import pytest
from blob_s3 import DELETE_BATCH_SIZE, S3BlobAdapter, S3BlobSettings
from foundation.blob import (
    BlobConflictError,
    BlobNotFoundError,
    BlobPresignOptions,
    BlobProviderError,
    BlobPutOptions,
)
from foundation.blob.conformance import (
    BLOB_ADAPTER_CHECKS,
    BlobCheckSkipped,
    BlobSuiteContext,
)
from s3_fakes import FakeS3Client, client_error

_counter = itertools.count()


def _settings(**overrides: object) -> S3BlobSettings:
    values: dict[str, object] = {
        'AWS_ENDPOINT_URL': 'http://localhost:19000',
        'AWS_REGION': 'us-east-1',
        'AWS_ACCESS_KEY_ID': 'test-key',
        'AWS_SECRET_ACCESS_KEY': 'test-secret',
        'AWS_S3_FORCE_PATH_STYLE': None,
    }
    values.update(overrides)
    return S3BlobSettings(**values)  # type: ignore[arg-type]


@pytest.fixture
async def fake_ctx() -> BlobSuiteContext:
    adapter = S3BlobAdapter(_settings(), client=FakeS3Client(), presign_expires=900)
    await adapter.ensure_bucket('suite-bucket')
    return BlobSuiteContext(
        adapter=adapter,
        bucket='suite-bucket',
        new_bucket_name=lambda: f'suite-new-{next(_counter)}',
    )


@pytest.mark.parametrize('check', sorted(BLOB_ADAPTER_CHECKS))
async def test_behaviour_with_fake_client(
    check: str, fake_ctx: BlobSuiteContext
) -> None:
    try:
        await BLOB_ADAPTER_CHECKS[check](fake_ctx)
    except BlobCheckSkipped as e:
        pytest.skip(str(e))


# ── settings ────────────────────────────────────────────────────────────────


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        'AWS_ENDPOINT_URL',
        'AWS_REGION',
        'AWS_DEFAULT_REGION',
        'AWS_S3_FORCE_PATH_STYLE',
    ):
        monkeypatch.delenv(key, raising=False)
    settings = S3BlobSettings()
    assert settings.endpoint_url is None
    assert settings.AWS_REGION == 'us-east-1'
    assert settings.force_path_style is False

    monkeypatch.setenv('AWS_DEFAULT_REGION', 'eu-west-3')
    assert S3BlobSettings().AWS_REGION == 'eu-west-3'
    monkeypatch.setenv('AWS_REGION', 'auto')
    assert S3BlobSettings().AWS_REGION == 'auto'

    monkeypatch.setenv('AWS_ENDPOINT_URL', 'http://localhost:19000')
    assert S3BlobSettings().force_path_style is True  # default with an endpoint
    monkeypatch.setenv('AWS_S3_FORCE_PATH_STYLE', 'false')
    assert S3BlobSettings().force_path_style is False
    monkeypatch.setenv('AWS_S3_FORCE_PATH_STYLE', '')
    assert S3BlobSettings().force_path_style is True  # empty = unset
    monkeypatch.delenv('AWS_ENDPOINT_URL')
    monkeypatch.setenv('AWS_S3_FORCE_PATH_STYLE', 'true')
    assert S3BlobSettings().force_path_style is True


def test_client_config() -> None:
    path_style = S3BlobAdapter(_settings()).client_config()
    assert path_style.signature_version == 's3v4'  # pyright: ignore[reportAttributeAccessIssue]
    assert path_style.s3 == {'addressing_style': 'path'}  # pyright: ignore[reportAttributeAccessIssue]
    virtual = S3BlobAdapter(_settings(AWS_ENDPOINT_URL='')).client_config()
    assert virtual.s3 == {'addressing_style': 'auto'}  # pyright: ignore[reportAttributeAccessIssue]


# ── real presigning with a real aiobotocore client (offline) ──────────────


async def test_presign_get_is_path_style_sigv4() -> None:
    adapter = S3BlobAdapter(_settings(), presign_expires=900)
    try:
        url = await adapter.presign(
            'my-bucket',
            'dir/a b.txt',
            BlobPresignOptions(download_name='report "1".pdf'),
        )
    finally:
        await adapter.aclose()
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == 'localhost:19000'
    assert parts.path == '/my-bucket/dir/a%20b.txt'
    assert query['X-Amz-Algorithm'] == ['AWS4-HMAC-SHA256']
    assert query['X-Amz-Expires'] == ['900']
    assert query['X-Amz-Credential'][0].startswith('test-key/')
    assert query['response-content-disposition'] == [
        'attachment; filename="report _1_.pdf"'
    ]


async def test_presign_put_signs_content_type() -> None:
    adapter = S3BlobAdapter(_settings(AWS_ENDPOINT_URL='', AWS_REGION='eu-west-3'))
    try:
        url = await adapter.presign(
            'my-bucket',
            'up.txt',
            BlobPresignOptions(method='PUT', content_type='text/plain', expires_in=60),
        )
    finally:
        await adapter.aclose()
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc.startswith('my-bucket.s3.') and parts.netloc.endswith(
        'amazonaws.com'
    )  # virtual-hosted
    assert '/eu-west-3/s3/aws4_request' in query['X-Amz-Credential'][0]
    assert query['X-Amz-Expires'] == ['60']
    assert 'content-type' in query['X-Amz-SignedHeaders'][0]


# ── S3 specifics with the fake client ─────────────────────────────────────


async def test_put_sends_options() -> None:
    fake = FakeS3Client()
    adapter = S3BlobAdapter(_settings(), client=fake)
    await adapter.ensure_bucket('bucket-a')
    info = await adapter.put(
        'bucket-a',
        'k.txt',
        'x',
        BlobPutOptions(
            content_type='text/plain',
            metadata={'A': '1'},
            cache_control='no-cache',
            content_disposition='inline',
        ),
    )
    _, params = next(c for c in fake.calls if c[0] == 'put_object')
    assert params['ContentType'] == 'text/plain'
    assert params['Metadata'] == {'a': '1'}
    assert params['CacheControl'] == 'no-cache'
    assert params['ContentDisposition'] == 'inline'
    assert info.etag is not None and '"' not in info.etag


async def test_delete_many_batches_of_1000() -> None:
    fake = FakeS3Client()
    adapter = S3BlobAdapter(_settings(), client=fake)
    await adapter.ensure_bucket('bucket-a')
    keys = [f'k/{i:05d}' for i in range(2500)]
    for key in keys[:3]:
        await adapter.put('bucket-a', key, b'x')
    await adapter.delete_many('bucket-a', keys)
    batches = [
        len(params['Delete']['Objects'])
        for name, params in fake.calls
        if name == 'delete_objects'
    ]
    assert batches == [DELETE_BATCH_SIZE, DELETE_BATCH_SIZE, 500]
    assert all(
        params['Delete']['Quiet']
        for name, params in fake.calls
        if name == 'delete_objects'
    )


async def test_delete_many_reports_errors() -> None:
    fake = FakeS3Client()
    adapter = S3BlobAdapter(_settings(), client=fake)
    await adapter.ensure_bucket('bucket-a')

    async def failing(**_kw: object) -> dict[str, object]:
        return {'Errors': [{'Key': 'k', 'Code': 'AccessDenied', 'Message': 'denied'}]}

    fake.delete_objects = failing  # type: ignore[method-assign]
    with pytest.raises(BlobProviderError, match='AccessDenied'):
        await adapter.delete_many('bucket-a', ['k'])


async def test_ensure_bucket_location_and_conflicts() -> None:
    fake = FakeS3Client(other_account_buckets={'taken-bucket'})
    aws = S3BlobAdapter(
        _settings(AWS_ENDPOINT_URL='', AWS_REGION='eu-west-3'), client=fake
    )
    await aws.ensure_bucket('bucket-a')
    _, params = fake.calls[-1]
    assert params['CreateBucketConfiguration'] == {'LocationConstraint': 'eu-west-3'}
    with pytest.raises(BlobConflictError):
        await aws.ensure_bucket('taken-bucket')

    rustfs = S3BlobAdapter(_settings(), client=fake)
    await rustfs.ensure_bucket('bucket-b')
    _, params = fake.calls[-1]
    assert 'CreateBucketConfiguration' not in params


async def test_error_mapping() -> None:
    fake = FakeS3Client()
    adapter = S3BlobAdapter(_settings(), client=fake)
    with pytest.raises(BlobNotFoundError):
        await adapter.put('missing-bucket', 'k', b'x')
    assert await adapter.head('missing-bucket', 'k') is None

    async def boom(**_kw: object) -> None:
        raise client_error('InternalError', 'GetObject', 500)

    fake.get_object = boom  # type: ignore[method-assign]
    with pytest.raises(BlobProviderError, match='s3 get failed'):
        await adapter.get('bucket-a', 'k')


async def test_injected_client_not_closed() -> None:
    fake = FakeS3Client()
    adapter = S3BlobAdapter(_settings(), client=fake)
    await adapter.aclose()
    await adapter.ensure_bucket('bucket-a')  # still usable
    assert adapter.provider == 's3'
