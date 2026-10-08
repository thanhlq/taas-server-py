"""Register :class:`foundation.http.BaseController` instances with Litestar."""
from __future__ import annotations

import inspect
from typing import Any, Callable, Iterable

from foundation.http import BaseController, Route, WebSocketRoute
from litestar import Litestar, Router, WebSocket
from litestar.handlers import HTTPRouteHandler, WebsocketRouteHandler

from http_litestar.adapters._dependencies import _make_wrapper, adapt_handler, typed_path
from http_litestar.adapters._websocket import LitestarWebSocketSession
from http_litestar.middewares.slowapi_ratelimit import rate_limit_guard


def _without_body(handler: Any) -> Any:
    """No-content statuses: Litestar refuses a handler that declares a return value (FastAPI ignores it), so the
    handler is re-wrapped with ``-> None`` when it declares something else."""
    signature = inspect.signature(handler)
    if signature.return_annotation in (None, type(None), "None"):
        return handler
    annotations = {**getattr(handler, "__annotations__", {}), "return": None}
    return _make_wrapper(handler, signature.replace(return_annotation=None), annotations)


def build_handler_for_route(route: Route) -> HTTPRouteHandler:
    """Convert a framework-agnostic :class:`Route` to a Litestar handler.

    Sync handlers are not offloaded to a thread by default — the contracts in
    ``foundation.http`` describe lightweight route handlers; explicit
    offloading can be set per-route via ``extra={'sync_to_thread': True}``.
    """
    handler, dependencies = adapt_handler(route.handler)
    is_async = inspect.iscoroutinefunction(handler)
    if route.status_code is not None and (route.status_code < 200 or route.status_code in (204, 304)):
        handler = _without_body(handler)

    kwargs: dict[str, Any] = {
        "path": typed_path(route.path, getattr(handler, "__annotations__", {})),
        "http_method": list(route.methods),
    }
    if not is_async and "sync_to_thread" not in route.extra:
        kwargs["sync_to_thread"] = False
    if route.name:
        kwargs["name"] = route.name
    if route.summary:
        kwargs["summary"] = route.summary
    if route.description:
        kwargs["description"] = route.description
    # Same default as FastAPI (200 for every method); Litestar would answer POST 201 / DELETE 204, and refuses a
    # DELETE handler with a response body under 204.
    kwargs["status_code"] = route.status_code if route.status_code is not None else 200
    if route.tags:
        kwargs["tags"] = list(route.tags)
    # ``extra`` carries framework-specific passthrough (guards, dependencies,
    # media_type, response_class, sync_to_thread overrides, ...).
    kwargs.update(route.extra)
    # Dependencies derived from FastAPI-style ``Depends`` markers; explicit
    # ``extra['dependencies']`` wins on key collisions.
    if dependencies:
        kwargs["dependencies"] = {**dependencies, **(kwargs.get("dependencies") or {})}

    # Per-route rate limiting: the limit string lives on ``route.rate_limit``.
    # Carry it (plus a stable bucket key) on the handler's ``opt`` and attach
    # the guard that enforces it against the app-wide limiter.
    if route.rate_limit:
        kwargs["opt"] = {
            **(kwargs.get("opt") or {}),
            "ratelimit": route.rate_limit,
            "ratelimit_key": route.path,
        }
        kwargs["guards"] = [*(kwargs.get("guards") or []), rate_limit_guard]

    return HTTPRouteHandler(**kwargs)(handler)


def build_ws_handler_for_route(ws: WebSocketRoute) -> WebsocketRouteHandler:
    """Convert a framework-agnostic :class:`WebSocketRoute` to a Litestar handler.

    Litestar injects the socket into a parameter named ``socket`` (typed
    ``WebSocket``); we wrap it in :class:`LitestarWebSocketSession` so the
    business handler stays framework-agnostic.
    """
    user_handler: Callable[..., Any] = ws.handler

    # No functools.wraps: it sets ``__wrapped__``, which would make Litestar's
    # signature model follow through to the business handler's
    # ``WebSocketSession`` annotation instead of seeing ``socket: WebSocket``.
    async def endpoint(socket: WebSocket) -> None:
        await user_handler(LitestarWebSocketSession(socket))

    kwargs: dict[str, Any] = {"path": ws.path}
    if ws.name:
        kwargs["name"] = ws.name
    kwargs.update(ws.extra)
    return WebsocketRouteHandler(**kwargs)(endpoint)


def _router_kwargs(
    controller: BaseController, overrides: dict[str, Any]
) -> dict[str, Any]:
    # Litestar requires a Router path; default to "/" when no prefix is set. A prefix may hold path parameters
    # (``/api/v1/sites/{site_id}/pages``): Litestar needs them typed, like the route paths (``str`` here).
    kwargs: dict[str, Any] = {
        "path": typed_path(controller.api_prefix.rstrip("/") or "/", {}),
    }
    if controller.tags:
        kwargs["tags"] = list(controller.tags)
    kwargs.update(overrides)
    return kwargs


def build_router_for_controller(
    controller: BaseController,
    **router_kwargs: Any,
) -> Router:
    """Build a :class:`Router` populated with the controller's routes."""
    handlers: list[Any] = [build_handler_for_route(r) for r in controller.get_routes()]
    handlers.extend(
        build_ws_handler_for_route(ws) for ws in controller.get_websocket_routes()
    )
    kwargs = _router_kwargs(controller, router_kwargs)
    kwargs.setdefault("route_handlers", handlers)
    return Router(**kwargs)


def include_controller(
    app: Litestar,
    controller: BaseController,
    **router_kwargs: Any,
) -> Router:
    """Build a router for ``controller`` and register it with ``app``."""
    router = build_router_for_controller(controller, **router_kwargs)
    app.register(router)
    return router


def register_controllers(
    controllers: Iterable[BaseController],
) -> list[Router]:
    """Build routers for multiple controllers without an app instance.

    Useful for the ``route_handlers=[...]`` argument of :class:`Litestar` at
    construction time, which is the recommended path in Litestar.
    """
    return [build_router_for_controller(c) for c in controllers]
