"""File bytes in the tenant's private storage, kind ``document`` (storage spec §2.2), through the storage
resolver (``ews.shared.tenant_root``) — never a bucket picked here.

- Key of a version: ``documents/drives/{drive_id}/{node_id}/{version_id}`` (no user-provided name; immutable).
- Download / preview: ``proxy`` = signed EWS URL ``/api/v1/files/content/{token}`` (1–5 min) streaming the bytes;
  ``presigned`` = a provider-signed GET URL with the same lifetime (Sto-0200, Sto-0201).
- Direct upload to ``documents/staging/{drive_id}/{version_id}``: ``proxy`` = ``PUT /api/v1/files/uploads/{token}``;
  ``presigned`` = a provider-signed PUT URL; ``complete`` copies it to the version key.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from foundation.blob import (
    BlobPresignOptions,
    BlobPutOptions,
    TenantBlobStoreT,
    kind_key,
)

from ews.shared import sign_token, tenant_root, verify_token

from ._rules import content_disposition
from ._settings import FilesSettings, files_settings

CONTENT_PURPOSE = 'files.content'
UPLOAD_PURPOSE = 'files.upload'


def version_key(
    drive_id: UUID | str, node_id: UUID | str, version_id: UUID | str
) -> str:
    return kind_key('document', f'drives/{drive_id}/{node_id}/{version_id}')


def staging_key(drive_id: UUID | str, version_id: UUID | str) -> str:
    """Target of a direct upload until ``complete`` copies it to its version key (incomplete ones: lifecycle rule)."""
    return kind_key('document', f'staging/{drive_id}/{version_id}')


async def store_for(tenant_id: UUID) -> TenantBlobStoreT:
    return await tenant_root(tenant_id)


async def put_bytes(tenant_id: UUID, key: str, body: bytes, mime: str) -> None:
    store = await store_for(tenant_id)
    await store.put(key, body, BlobPutOptions(content_type=mime))


async def delete_keys(tenant_id: UUID, keys: list[str]) -> None:
    if keys:
        await (await store_for(tenant_id)).delete_many(keys)


def _expiry(seconds: int, now: float | None = None) -> int:
    return int((now if now is not None else time.time()) + seconds)


def as_datetime(exp: int) -> datetime:
    return datetime.fromtimestamp(exp, UTC)


# --- downloads ------------------------------------------------------------------------------------


def read_content_token(token: str) -> dict[str, Any] | None:
    return verify_token(token, purpose=CONTENT_PURPOSE)


async def content_url(
    tenant_id: UUID,
    key: str,
    mime: str,
    filename: str,
    *,
    inline: bool,
    settings: FilesSettings | None = None,
) -> tuple[str, int]:
    """``(url, exp)`` of a short-lived download / preview URL (the caller checked the permission)."""
    settings = settings or files_settings()
    exp = _expiry(settings.url_ttl_seconds)
    if settings.delivery == 'presigned':
        store = await store_for(tenant_id)
        url = await store.presign(
            key,
            BlobPresignOptions(
                method='GET',
                expires_in=settings.url_ttl_seconds,
                download_name=None if inline else filename,
            ),
        )
        return url, exp
    payload = {
        't': str(tenant_id),
        'k': key,
        'm': mime,
        'f': filename,
        'i': inline,
        'exp': exp,
    }
    return (
        f'{settings.public_base_url}/api/v1/files/content/{sign_token(payload, purpose=CONTENT_PURPOSE)}',
        exp,
    )


def content_headers(
    mime: str, filename: str, *, inline: bool, etag: str | None = None
) -> dict[str, str]:
    """Headers of a proxied file: risky types are always attachments, never sniffed (Sto-0202)."""
    headers = {
        'content-disposition': content_disposition(filename, inline=inline),
        'x-content-type-options': 'nosniff',
        'cache-control': 'private, no-store',
        'cross-origin-resource-policy': 'cross-origin',
    }
    if inline and mime != 'application/pdf':
        headers['content-security-policy'] = (
            "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox"
        )
    if etag:
        headers['etag'] = f'"{etag}"'
    return headers


# --- direct uploads -------------------------------------------------------------------------------


def upload_token(
    payload: dict[str, Any], settings: FilesSettings | None = None
) -> tuple[str, int]:
    settings = settings or files_settings()
    exp = _expiry(settings.upload_ttl_seconds)
    return sign_token({**payload, 'exp': exp}, purpose=UPLOAD_PURPOSE), exp


def read_upload_token(token: str) -> dict[str, Any] | None:
    return verify_token(token, purpose=UPLOAD_PURPOSE)


async def upload_url(
    tenant_id: UUID,
    key: str,
    mime: str,
    token: str,
    settings: FilesSettings | None = None,
) -> str:
    settings = settings or files_settings()
    if settings.delivery == 'presigned':
        store = await store_for(tenant_id)
        return await store.presign(
            key,
            BlobPresignOptions(
                method='PUT', expires_in=settings.upload_ttl_seconds, content_type=mime
            ),
        )
    return f'{settings.public_base_url}/api/v1/files/uploads/{token}'
