from __future__ import annotations

from contextvars import ContextVar, Token

from platform_core.http.context import Context

_REQUEST_CONTEXT: ContextVar[Context | None] = ContextVar("request_context", default=None)


def set_request_context(ctx: Context) -> Token[Context | None]:
    return _REQUEST_CONTEXT.set(ctx)


def get_request_context() -> Context | None:
    return _REQUEST_CONTEXT.get()


def require_request_context() -> Context:
    ctx = get_request_context()
    if ctx is None:
        raise RuntimeError("Request Context is not available for the current execution")
    return ctx
