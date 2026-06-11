from __future__ import annotations

from fastapi import HTTPException
from platform_core.http.context import Context
from platform_core.http.context_state import (
    require_request_context,
    set_request_context,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_RESERVED_HEADERS = {"content-length", "content-type"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Create a per-request Context and keep it available during handler execution."""

    async def dispatch(self, request: Request, call_next):
        ctx = Context()
        ctx.req = request
        # Controllers can mutate this response object (headers/cookies/status).
        # Changes are merged into the real outbound response after the handler returns.
        ctx.res = Response()
        request.state.ctx = ctx

        token = set_request_context(ctx)
        try:
            response = await call_next(request)
            _merge_context_response(ctx.res, response)
            return response
        finally:
            token.var.reset(token)


def _merge_context_response(ctx_response: Response, response: Response) -> None:
    if ctx_response.status_code != 200 and response.status_code == 200:
        response.status_code = ctx_response.status_code

    for key, value in ctx_response.headers.items():
        if key.lower() in _RESERVED_HEADERS:
            continue
        response.headers[key] = value

    for key, value in ctx_response.raw_headers:
        lower = key.lower()
        if lower in (b"content-length", b"content-type"):
            continue
        if lower == b"set-cookie":
            response.headers.append("set-cookie", value.decode("latin-1"))


def get_request_context() -> Context:
    """FastAPI dependency for handlers that declare ``ctx: Context``."""
    try:
        return require_request_context()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
