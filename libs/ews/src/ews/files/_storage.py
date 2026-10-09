"""File bytes in the tenant's private storage (storage spec §2.2), through the storage resolver
(``ews.shared.tenant_root``) — never a bucket picked here. Keys are built from ids only (never user names) and are
immutable: renames and moves are database updates.

- Version: ``documents/drives/{drive_id}/{node_id}/{version_id}`` (kind ``document``).
- Generated variant: ``derived/files/{node_id}/{version_id}/{variant}.webp`` (kind ``derived``, ``_pipeline``).
- Direct upload to ``documents/staging/{drive_id}/{version_id}``: ``proxy`` = ``PUT /api/v1/files/uploads/{token}``;
  ``presigned`` = a provider-signed PUT URL; ``complete`` copies it to the version key.
- Download / view URLs: ``_delivery``.
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

from ._settings import FilesSettings, files_settings

UPLOAD_PURPOSE = 'files.upload'


def version_key(
    drive_id: UUID | str, node_id: UUID | str, version_id: UUID | str
) -> str:
    return kind_key('document', f'drives/{drive_id}/{node_id}/{version_id}')


def preview_key(node_id: UUID | str, version_id: UUID | str, variant: str) -> str:
    """A generated variant of a version (thumbnail, preview rendition)."""
    return kind_key('derived', f'files/{node_id}/{version_id}/{variant}.webp')


def staging_key(drive_id: UUID | str, version_id: UUID | str) -> str:
    """Target of a direct upload until ``complete`` copies it to its version key (incomplete ones: lifecycle rule)."""
    return kind_key('document', f'staging/{drive_id}/{version_id}')


async def store_for(tenant_id: UUID) -> TenantBlobStoreT:
    return await tenant_root(tenant_id)


IMMUTABLE_PRIVATE = 'private, max-age=31536000, immutable'
"""Cache header stored on generated variants (keys are never reused): honoured by provider-signed GETs."""


async def put_bytes(
    tenant_id: UUID,
    key: str,
    body: bytes,
    mime: str,
    *,
    cache_control: str | None = None,
) -> None:
    store = await store_for(tenant_id)
    await store.put(
        key, body, BlobPutOptions(content_type=mime, cache_control=cache_control)
    )


async def delete_keys(tenant_id: UUID, keys: list[str]) -> None:
    if keys:
        await (await store_for(tenant_id)).delete_many(keys)


def _expiry(seconds: int, now: float | None = None) -> int:
    return int((now if now is not None else time.time()) + seconds)


def as_datetime(exp: int) -> datetime:
    return datetime.fromtimestamp(exp, UTC)


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
