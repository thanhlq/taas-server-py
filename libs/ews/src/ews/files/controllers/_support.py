"""Request helpers of the File Manager controllers."""

from __future__ import annotations

from typing import Any

from foundation.exceptions import ClientException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from foundation.http.context import Context

from ews.shared import read_form

from .._settings import files_settings

ON_CONFLICT = ('version', 'keep_both', 'skip')


async def multipart_file(ctx: Context) -> tuple[bytes, str | None, Any]:
    """``(bytes, filename, form)`` of a multipart ``file`` field (size checked before and after reading)."""
    limit = files_settings().max_upload_bytes
    length = ctx.req.headers.get('content-length')
    if length and length.isdigit() and int(length) > limit + 64 * 1024:
        raise RequestEntityTooLarge(
            detail='file too large', extra={'code': 'too_large'}
        )
    form = await read_form(ctx.req)
    upload = form.get('file')
    if upload is None or not hasattr(upload, 'read'):
        raise ClientException(detail='multipart field "file" is required')
    data = await upload.read()
    return data, getattr(upload, 'filename', None), form


def field(form: Any, name: str) -> str | None:
    value = form.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def on_conflict(form: Any) -> str:
    value = field(form, 'on_conflict') or 'version'
    if value not in ON_CONFLICT:
        raise ClientException(
            detail=f'on_conflict must be one of {", ".join(ON_CONFLICT)}'
        )
    return value
