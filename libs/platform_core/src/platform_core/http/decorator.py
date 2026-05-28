"""Decorators that mark methods as HTTP route handlers.

Each decorator attaches a :class:`Route` to the wrapped function via the
``__platform_core_route__`` attribute. A :class:`Controller` later collects
these and exposes them through :meth:`Controller.get_routes`.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from platform_core.http.route import (
    HttpMethod,
    Route,
    SocketIOHandler,
    WebSocketRoute,
)

ROUTE_ATTR = "__platform_core_route__"
WS_ROUTE_ATTR = "__platform_core_ws_route__"
SIO_HANDLER_ATTR = "__platform_core_sio_handler__"


def route(
    path: str,
    methods: Sequence[HttpMethod],
    *,
    name: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    response_model: Any = None,
    status_code: int | None = None,
    tags: Sequence[str] | None = None,
    permissions: Sequence[str] | None = None,
    middleware: Sequence[Any] | None = None,
    ratelimit: str | None = None,
    **extra: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        meta = Route(
            path=path,
            methods=tuple(methods),
            handler=func,
            name=name,
            summary=summary,
            description=description,
            response_model=response_model,
            status_code=status_code,
            tags=tuple(tags) if tags is not None else None,
            permissions=tuple(permissions) if permissions is not None else None,
            middleware=tuple(middleware) if middleware is not None else None,
            rate_limit=ratelimit,
            extra=dict(extra),
        )
        setattr(func, ROUTE_ATTR, meta)
        return func
    return decorator


def get(path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return route(path, ("GET",), **kwargs)


def post(path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return route(path, ("POST",), **kwargs)


def put(path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return route(path, ("PUT",), **kwargs)


def delete(path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return route(path, ("DELETE",), **kwargs)


def patch(path: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return route(path, ("PATCH",), **kwargs)


def websocket(
    path: str,
    *,
    name: str | None = None,
    permissions: Sequence[str] | None = None,
    middleware: Sequence[Any] | None = None,
    **extra: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a coroutine as a WebSocket route handler.

    The handler must be ``async`` and accept a single
    :class:`~platform_core.http.websocket.WebSocketSession` argument (after
    ``self``). Framework-specific options can be forwarded via ``**extra``.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        meta = WebSocketRoute(
            path=path,
            handler=func,
            name=name,
            permissions=tuple(permissions) if permissions is not None else None,
            middleware=tuple(middleware) if middleware is not None else None,
            extra=dict(extra),
        )
        setattr(func, WS_ROUTE_ATTR, meta)
        return func
    return decorator


def socketio_event(
    event: str,
    *,
    namespace: str = '/',
    name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a coroutine as a Socket.IO event handler.

    The handler must be ``async`` and accept ``(self, session, data=None)``
    where ``session`` is a
    :class:`~platform_core.http._socketio.SocketIOSession`. ``event`` is the
    Socket.IO event name (``connect``, ``disconnect``, or a custom event such
    as ``subscribe``); ``data`` is the event payload (the ``auth`` mapping for
    ``connect``).
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        meta = SocketIOHandler(
            event=event,
            handler=func,
            namespace=namespace,
            name=name,
        )
        setattr(func, SIO_HANDLER_ATTR, meta)
        return func
    return decorator
