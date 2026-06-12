from __future__ import annotations

from platform_core.http.context import Context
from platform_core.http.context_state import (
    require_request_context,
    set_request_context,
)
from platform_core.types import ASGIApp, Scope
from platform_core.types.asgi_types import Receive, Send
from starlette.requests import Request
from starlette.responses import Response

_RESERVED_HEADERS = {b"content-length", b"content-type"}


class RequestContextMiddleware:
    """Create a per-request Context and keep it available during handler execution."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        ctx = Context()
        ctx.req = Request(scope, receive=receive)
        # Controllers can mutate this response object (headers/cookies/status).
        # Changes are merged into the real outbound response in send wrapper.
        ctx.res = Response()
        ctx.pack()

        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["ctx"] = ctx

        token = set_request_context(ctx)
        try:
            await self.app(scope, receive, _wrap_send(send, ctx.res))
        finally:
            token.var.reset(token)


def _wrap_send(send: Send, ctx_response: Response) -> Send:
    async def _send(message):
        if message.get("type") == "http.response.start":
            status = message.get("status", 200)
            if ctx_response.status_code != 200 and status == 200:
                status = ctx_response.status_code

            headers = list(message.get("headers", []))
            _merge_headers(headers, ctx_response.raw_headers)

            message = {
                **message,
                "status": status,
                "headers": headers,
            }

        await send(message)

    return _send


def _merge_headers(target: list[tuple[bytes, bytes]], extra: tuple[tuple[bytes, bytes], ...]) -> None:
    for key, value in extra:
        key_lower = key.lower()
        if key_lower in _RESERVED_HEADERS:
            continue
        if key_lower == b"set-cookie":
            target.append((key, value))
            continue

        target[:] = [(k, v) for (k, v) in target if k.lower() != key_lower]
        target.append((key, value))


def get_request_context() -> Context:
    return require_request_context()
