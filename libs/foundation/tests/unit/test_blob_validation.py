"""foundation.blob: validation helpers, errors, settings (no I/O)."""

from __future__ import annotations

import pytest
from foundation.blob import (
    BlobConflictError,
    BlobError,
    BlobInfo,
    BlobListOptions,
    BlobNotFoundError,
    BlobPresignOptions,
    BlobProviderError,
    BlobSettings,
    BlobTenantNotFoundError,
    BlobValidationError,
    attachment_disposition,
    body_to_bytes,
    normalize_metadata,
    normalize_provider,
    resolve_presign_expires,
    strip_etag,
    validate_bucket_name,
    validate_key,
    validate_keys,
    validate_list_options,
    validate_metadata,
)


@pytest.mark.parametrize(
    'key',
    [
        'a',
        'a.txt',
        'projects/p1/file.pdf',
        'tasks/t1/attachments/ünïcode name.txt',
        '.hidden',
        'a..b',
        'x' * 1024,
    ],
)
def test_valid_keys(key: str) -> None:
    assert validate_key(key) == key


@pytest.mark.parametrize(
    'key',
    [
        '',
        '/abs',
        'a//b',
        'a/',
        'a/./b',
        './a',
        'a/..',
        '..',
        '.',
        'ctl\x00x',
        'tab\tx',
        'del\x7fx',
        'c1\x85x',
        'x' * 1025,
        'é' * 513,
    ],
)
def test_invalid_keys(key: str) -> None:
    with pytest.raises(BlobValidationError):
        validate_key(key)


@pytest.mark.parametrize(
    'bucket', ['abc', 'taas-12345678', 'e2e-py-0001', '0ab', 'a' * 63]
)
def test_valid_buckets(bucket: str) -> None:
    assert validate_bucket_name(bucket) == bucket


@pytest.mark.parametrize(
    'bucket',
    ['', 'ab', 'Abc', '-abc', 'abc-', 'a_b', 'a.b', 'a' * 64, 'ab c', 'taas--1234'],
)
def test_invalid_buckets(bucket: str) -> None:
    with pytest.raises(BlobValidationError):
        validate_bucket_name(bucket)


def test_validate_keys_dedupes_in_order() -> None:
    assert validate_keys(['b', 'a', 'b']) == ['b', 'a']
    with pytest.raises(BlobValidationError):
        validate_keys(['ok', '/bad'])


def test_list_options() -> None:
    assert validate_list_options(None).limit == 1000
    assert validate_list_options(BlobListOptions(limit=1)).limit == 1
    for limit in (0, 1001, -1):
        with pytest.raises(BlobValidationError):
            validate_list_options(BlobListOptions(limit=limit))
    assert (
        validate_list_options(BlobListOptions(prefix='projects/')).prefix == 'projects/'
    )


def test_presign_expires() -> None:
    assert resolve_presign_expires(BlobPresignOptions(), 900) == 900
    assert resolve_presign_expires(BlobPresignOptions(expires_in=1), 900) == 1
    assert resolve_presign_expires(BlobPresignOptions(expires_in=604800), 900) == 604800
    for expires in (0, 604801):
        with pytest.raises(BlobValidationError):
            resolve_presign_expires(BlobPresignOptions(expires_in=expires), 900)


def test_body_metadata_disposition_etag() -> None:
    assert body_to_bytes('héllo') == 'héllo'.encode()
    assert body_to_bytes(b'\x00') == b'\x00'
    # reads: lenient lower-casing; writes: lower-cased then ^[a-z][a-z0-9_]{0,62}$
    assert normalize_metadata({'Project-Id': 'a'}) == {'project-id': 'a'}
    assert validate_metadata({'Owner': 'a', 'Project_ID': 'b'}) == {
        'owner': 'a',
        'project_id': 'b',
    }
    assert validate_metadata(None) == {}
    for bad in ('project-id', '1st', '_x', 'a b', '', 'x' * 64, 'é'):
        with pytest.raises(BlobValidationError):
            validate_metadata({bad: 'v'})
    # download name: ", \\ and control characters replaced by _
    assert attachment_disposition('report.pdf') == 'attachment; filename="report.pdf"'
    assert (
        attachment_disposition('a"b\\c\nd\x85e') == 'attachment; filename="a_b_c_d_e"'
    )
    assert attachment_disposition('résumé.pdf') == 'attachment; filename="résumé.pdf"'
    assert strip_etag('"abc"') == 'abc'
    assert strip_etag('W/"abc"') == 'abc'
    assert strip_etag(None) is None


def test_error_codes() -> None:
    assert BlobValidationError('x').code == 'invalid_blob_request'
    assert BlobNotFoundError('x').code == 'blob_not_found'
    assert BlobConflictError('x').code == 'blob_conflict'
    assert BlobTenantNotFoundError('x').code == 'blob_tenant_not_found'
    error = BlobProviderError('s3', 'put', RuntimeError('boom'))
    assert error.code == 'blob_provider_error'
    assert str(error) == 's3 put failed: boom'
    assert (error.provider, error.operation) == ('s3', 'put')
    assert all(
        issubclass(c, BlobError) for c in (BlobValidationError, BlobProviderError)
    )
    assert isinstance(BlobValidationError('x'), ValueError)


def test_types_are_frozen() -> None:
    info = BlobInfo(bucket='b', key='k', size=1)
    assert info.metadata == {}
    with pytest.raises(AttributeError):
        info.size = 2  # type: ignore[misc]


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ('BLOB_STORAGE_PROVIDER', 'BLOB_BUCKET_PREFIX', 'BLOB_PRESIGN_EXPIRES'):
        monkeypatch.delenv(key, raising=False)
    settings = BlobSettings()
    assert settings.provider == 's3'
    assert settings.BLOB_BUCKET_PREFIX == 'taas-'
    assert settings.BLOB_PRESIGN_EXPIRES == 900


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('BLOB_STORAGE_PROVIDER', 'GCS')
    monkeypatch.setenv('BLOB_BUCKET_PREFIX', 'acme-prod-')
    monkeypatch.setenv('BLOB_PRESIGN_EXPIRES', '60')
    settings = BlobSettings()
    assert settings.provider == 'gcp'
    assert settings.BLOB_STORAGE_PROVIDER == 'gcp'
    assert settings.BLOB_BUCKET_PREFIX == 'acme-prod-'
    assert settings.BLOB_PRESIGN_EXPIRES == 60


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('BLOB_STORAGE_PROVIDER', 'fs'),
        ('BLOB_BUCKET_PREFIX', 'Bad_'),
        ('BLOB_BUCKET_PREFIX', '-x'),
        ('BLOB_BUCKET_PREFIX', 'x' * 56),
        ('BLOB_PRESIGN_EXPIRES', 0),
    ],
)
def test_settings_invalid(field: str, value: object) -> None:
    with pytest.raises(BlobValidationError):
        BlobSettings(**{field: value})  # type: ignore[arg-type]


def test_normalize_provider() -> None:
    assert [
        normalize_provider(p) for p in ('s3', 'gcp', 'gcs', 'azure', 'memory', ' S3 ')
    ] == [
        's3',
        'gcp',
        'gcp',
        'azure',
        'memory',
        's3',
    ]
