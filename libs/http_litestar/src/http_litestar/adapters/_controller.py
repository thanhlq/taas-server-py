"""Register :class:`platform_core.http.BaseController` instances with Litestar."""
from __future__ import annotations

import inspect
from typing import Any, Callable, Iterable

from litestar import Litestar, Router, WebSocket
from litestar.handlers import HTTPRouteHandler, WebsocketRouteHandler
from platform_core.http import BaseController, Route, WebSocketRoute

from http_litestar.adapters._websocket import LitestarWebSocketSession


def _strip_injected_cache_params(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Hide synthetic ``request``/``response`` params added by ``@cache``.

    ``platform_core.http.cache`` injects ``request``/``response`` into the
    handler's ``__signature__`` so FastAPI can supply them. Litestar resolves
    parameter types via ``typing.get_type_hints`` (``__annotations__``) and the
    synthetic params are not present there, so it raises "does not have a type
    annotation". We present Litestar a wrapper whose signature omits the
    injected params; the underlying ``@cache`` wrapper still accepts them and
    simply receives ``None`` (cache-control header honouring is skipped).
    """
    injected = getattr(handler, "__cache_injected_params__", None)
    if not injected:
        return handler

    original_sig = inspect.signature(handler)
    kept = [p for name, p in original_sig.parameters.items() if name not in injected]
    new_sig = original_sig.replace(parameters=kept)
    original_hints = getattr(handler, "__annotations__", {}) or {}
    new_annotations = {
        name: original_hints[name]
        for name in (p.name for p in kept)
        if name in original_hints
    }
    if "return" in original_hints:
        new_annotations["return"] = original_hints["return"]

    if inspect.iscoroutinefunction(handler):

        async def adapted(*args: Any, **kwargs: Any) -> Any:
            return await handler(*args, **kwargs)
    else:

        def adapted(*args: Any, **kwargs: Any) -> Any:
            return handler(*args, **kwargs)

    # Deliberately no functools.wraps: it would set ``__wrapped__`` and make
    # Litestar follow through to the original injected signature.
    adapted.__name__ = getattr(handler, "__name__", "adapted")
    adapted.__doc__ = getattr(handler, "__doc__", None)
    # Resolve forward references against the controller's module, not ours.
    adapted.__module__ = getattr(handler, "__module__", adapted.__module__)
    adapted.__signature__ = new_sig  # type: ignore[attr-defined]
    adapted.__annotations__ = new_annotations
    return adapted


def build_handler_for_route(route: Route) -> HTTPRouteHandler:
    """Convert a framework-agnostic :class:`Route` to a Litestar handler.

    Sync handlers are not offloaded to a thread by default — the contracts in
    ``platform_core.http`` describe lightweight route handlers; explicit
    offloading can be set per-route via ``extra={'sync_to_thread': True}``.
    """
    handler = _strip_injected_cache_params(route.handler)
    is_async = inspect.iscoroutinefunction(handler)

    kwargs: dict[str, Any] = {
        "path": route.path,
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
    if route.status_code is not None:
        kwargs["status_code"] = route.status_code
    if route.tags:
        kwargs["tags"] = list(route.tags)
    # ``extra`` carries framework-specific passthrough (guards, dependencies,
    # media_type, response_class, sync_to_thread overrides, ...).
    kwargs.update(route.extra)

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
    # Litestar requires a Router path; default to "/" when no prefix is set.
    kwargs: dict[str, Any] = {
        "path": controller.api_prefix.rstrip("/") or "/",
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
