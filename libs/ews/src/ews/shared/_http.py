from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from foundation.exceptions import ClientException, NotFoundException
from foundation.http.context_state import get_request_context


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_uuid(value: object, what: str = 'id', *, not_found: bool = True) -> UUID:
    """A path / body id as ``UUID``; malformed → 404 (path ids) or 400 (``not_found=False``)."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as error:
        if not_found:
            raise NotFoundException(detail=f'{what} not found') from error
        raise ClientException(detail=f'{what} must be a UUID') from error


def raw_response(
    body: bytes | str,
    *,
    media_type: str,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    request: Any = None,
) -> Any:
    """A non-JSON response for the framework serving ``request`` (Starlette / FastAPI or Litestar)."""
    module = type(request).__module__ if request is not None else ''
    if module.startswith('litestar'):
        from litestar import Response as LitestarResponse

        return LitestarResponse(content=body, media_type=media_type, status_code=status_code, headers=dict(headers or {}))
    from starlette.responses import Response

    return Response(content=body, media_type=media_type, status_code=status_code, headers=dict(headers or {}))



def file_response(body: bytes, media_type: str, name: str) -> Any:
    """A download (``content-disposition: attachment``, ``no-store``) of the current request's framework."""
    ctx = get_request_context()
    safe = re.sub(r'[^A-Za-z0-9._-]+', '-', name)[:120] or 'export'
    return raw_response(
        body,
        media_type=media_type,
        request=ctx.req if ctx else None,
        headers={'content-disposition': f'attachment; filename="{safe}"', 'cache-control': 'no-store'},
    )


async def read_form(request: Any) -> Mapping[str, Any]:
    """Multipart / urlencoded form of the request (Starlette and Litestar share ``await request.form()``)."""
    try:
        return await request.form()
    except Exception as error:  # malformed multipart, missing python-multipart, …
        raise ClientException(detail=f'invalid form data: {error}') from error
