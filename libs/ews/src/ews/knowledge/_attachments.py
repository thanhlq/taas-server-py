"""Page attachments (Kb-0305): private files in the tenant's storage kind ``knowledge/`` (through the storage
resolver — never a bucket picked here), delivered after the page's permission check through a signed URL valid
``FILE_URL_SECONDS`` (Sto-0200): ``presigned`` → the provider's URL, ``proxy`` → ``GET /api/v1/knowledge/files/{token}``
streams the bytes (``MEDIA_DELIVERY`` / ``MEDIA_PUBLIC_BASE_URL`` of the API).

Key: ``knowledge/<space_id>/<attachment_id>/<version>/original[.ext]``. Deleting an attachment (or its page) is a
soft delete; the blob is kept for the retention job (🚧).
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from db.models.knowledge import KbAttachment
from foundation.blob import BlobPresignOptions, BlobPutOptions, kind_key
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from sqlalchemy import select

from ews.media import media_settings
from ews.security import RequestScope
from ews.shared import (
    parse_uuid,
    sign_token,
    tenant_root,
    user_names,
    utcnow,
    verify_token,
)

from ._access import PageAccess
from ._rules import FILE_URL_SECONDS, MAX_ATTACHMENT_BYTES
from .schemas import KbAttachmentOut, KbDownloadOut

FILE_TOKEN_PURPOSE = 'kb.file'
INLINE_TYPES = frozenset(
    {
        'image/png',
        'image/jpeg',
        'image/gif',
        'image/webp',
        'application/pdf',
        'text/plain',
    }
)
"""Shown in the browser (``?inline=true``); every other type is always downloaded."""
_MIME = re.compile(r'^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$')
_EXT = re.compile(r'^[a-z0-9]{1,10}$')


def safe_filename(name: str | None) -> str:
    """Base name without path, control or quote characters (max 255), else ``file``."""
    base = re.split(r'[\\/]', name or '')[-1]
    clean = (
        ''.join(c for c in base if c.isprintable() and c not in '"<>|*?:')
        .strip()
        .strip('.')
    )
    return clean[:255] or 'file'


def content_disposition(filename: str) -> str:
    """``attachment`` with an ASCII fallback name and the UTF-8 name (RFC 6266 / 5987)."""
    fallback = (
        ''.join(
            c for c in filename if c.isascii() and c.isprintable() and c not in '"\\'
        )
        or 'file'
    )
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'


def clean_mime(content_type: str | None, filename: str) -> str:
    mime = (content_type or '').split(';', 1)[0].strip().lower()
    if not _MIME.match(mime) or mime == 'application/octet-stream':
        mime = (mimetypes.guess_type(filename)[0] or 'application/octet-stream').lower()
    return mime


def _ext(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return f'.{ext}' if _EXT.match(ext) else ''


def attachment_out(a: KbAttachment, names: dict[Any, str]) -> KbAttachmentOut:
    return KbAttachmentOut(
        id=str(a.id),
        page_id=str(a.page_id),
        filename=a.filename,
        mime=a.mime,
        size=a.size,
        created_by=str(a.created_by) if a.created_by else None,
        created_by_name=names.get(a.created_by) if a.created_by else None,
        created_at=a.created_at,
    )


async def list_attachments(
    session: DBAsyncScopedSession, pa: PageAccess
) -> list[KbAttachmentOut]:
    rows = list(
        await session.scalars(
            select(KbAttachment)
            .where(
                KbAttachment.page_id == pa.page.id, KbAttachment.deleted_at.is_(None)
            )
            .order_by(KbAttachment.created_at)
        )
    )
    names = await user_names(session, [a.created_by for a in rows])
    return [attachment_out(a, names) for a in rows]


async def get_attachment(
    session: DBAsyncScopedSession, pa: PageAccess, attachment_id: object
) -> KbAttachment:
    aid = parse_uuid(attachment_id, 'attachment')
    row = await session.scalar(
        select(KbAttachment).where(
            KbAttachment.id == aid,
            KbAttachment.page_id == pa.page.id,
            KbAttachment.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundException(detail='attachment not found')
    return row


async def upload(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    data: bytes,
    filename: str | None,
    content_type: str | None,
) -> KbAttachment:
    if not data:
        raise ClientException(detail='file is empty')
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise RequestEntityTooLarge(
            detail=f'attachments are limited to {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB'
        )
    name = safe_filename(filename)
    mime = clean_mime(content_type, name)
    attachment_id = uuid.uuid7()
    key = kind_key('knowledge', f'{pa.space.id}/{attachment_id}/1/original{_ext(name)}')
    store = await tenant_root(pa.page.tenant_id)
    await store.put(key, data, BlobPutOptions(content_type=mime))
    attachment = KbAttachment(
        id=attachment_id,
        tenant_id=pa.page.tenant_id,
        space_id=pa.space.id,
        page_id=pa.page.id,
        filename=name,
        mime=mime,
        size=len(data),
        key=key,
        checksum=hashlib.sha256(data).hexdigest(),
        version=1,
        created_by=scope.user_id,
    )
    session.add(attachment)
    await session.flush()
    return attachment


async def delete_attachment(
    session: DBAsyncScopedSession, attachment: KbAttachment
) -> None:
    attachment.deleted_at = utcnow()
    await session.flush()


def file_token(attachment: KbAttachment, *, inline: bool, exp: int) -> str:
    payload: dict[str, Any] = {
        't': str(attachment.tenant_id),
        'k': attachment.key,
        'm': attachment.mime,
        'exp': exp,
    }
    if not inline:
        payload['d'] = attachment.filename
    return sign_token(payload, purpose=FILE_TOKEN_PURPOSE)


def read_file_token(token: str) -> dict[str, Any] | None:
    return verify_token(token, purpose=FILE_TOKEN_PURPOSE)


async def download_url(
    attachment: KbAttachment, *, inline: bool = False
) -> KbDownloadOut:
    """A signed URL valid ``FILE_URL_SECONDS`` (call after the page's permission check)."""
    settings = media_settings()
    inline = inline and attachment.mime in INLINE_TYPES
    exp = int(time.time()) + FILE_URL_SECONDS
    if settings.delivery == 'presigned':
        store = await tenant_root(attachment.tenant_id)
        url = await store.presign(
            attachment.key,
            BlobPresignOptions(
                method='GET',
                expires_in=FILE_URL_SECONDS,
                download_name=None if inline else attachment.filename,
            ),
        )
    else:
        url = f'{settings.public_base_url}/api/v1/knowledge/files/{file_token(attachment, inline=inline, exp=exp)}'
    return KbDownloadOut(
        url=url,
        filename=attachment.filename,
        mime=attachment.mime,
        expires_at=datetime.fromtimestamp(exp, UTC),
    )


async def file_response_parts(token: str) -> tuple[bytes, str, dict[str, str]]:
    """``(body, media type, headers)`` of a signed file URL; 404 when expired, invalid or gone."""
    claims = read_file_token(token)
    if claims is None:
        raise NotFoundException(detail='link expired or invalid')
    store = await tenant_root(claims['t'])
    blob = await store.get(claims['k'])
    if blob is None:
        raise NotFoundException(detail='file not found')
    mime = claims.get('m') or 'application/octet-stream'
    headers = {
        'cache-control': f'private, max-age={FILE_URL_SECONDS}',
        'x-content-type-options': 'nosniff',
        'referrer-policy': 'no-referrer',
    }
    if claims.get('d') or mime not in INLINE_TYPES:
        headers['content-disposition'] = content_disposition(
            str(claims.get('d') or 'file')
        )
    if blob.info.etag:
        headers['etag'] = f'"{blob.info.etag}"'
    return blob.body, mime, headers
