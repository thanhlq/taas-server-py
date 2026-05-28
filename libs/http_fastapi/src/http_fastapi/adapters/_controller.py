"""Register :class:`platform_core.http.Controller` instances with FastAPI."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from fastapi import APIRouter, FastAPI
from platform_core.http import BaseController, Route, WebSocketRoute
from starlette.requests import Request
from starlette.websockets import WebSocket

from http_fastapi.adapters._websocket import FastAPIWebSocketSession
from http_fastapi.fastapi_msgspec.routing import MsgSpecRoute


def _router_kwargs(
    controller: BaseController, overrides: dict[str, Any]
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {'route_class': MsgSpecRoute}
    if controller.api_prefix:
        kwargs['prefix'] = controller.api_prefix.rstrip('/')
    if controller.tags:
        kwargs['tags'] = list(controller.tags)
    kwargs.update(overrides)
    return kwargs


def build_router_for_controller(
    controller: BaseController,
    *,
    app: FastAPI | None = None,
    **router_kwargs: Any,
) -> APIRouter:
    """Build an :class:`APIRouter` populated with the controller's routes.

    ``app`` is needed only to look up ``app.state.limiter`` for per-route rate
    limits; pass it when calling from :func:`include_controller`.
    """
    router = APIRouter(**_router_kwargs(controller, router_kwargs))
    limiter = getattr(getattr(app, 'state', None), 'limiter', None) if app else None
    for r in controller.get_routes():
        _add_route(router, r, limiter)
    for ws in controller.get_websocket_routes():
        _add_websocket_route(router, ws)
    return router


def include_controller(
    app: FastAPI,
    controller: BaseController,
    **router_kwargs: Any,
) -> APIRouter:
    """Build a router for ``controller`` and attach it to ``app``."""
    router = build_router_for_controller(controller, app=app, **router_kwargs)
    app.include_router(router)
    return router


def _add_route(router: APIRouter, route: Route, limiter: Any = None) -> None:
    kwargs: dict[str, Any] = {}
    if route.name:
        kwargs['name'] = route.name
    if route.summary:
        kwargs['summary'] = route.summary
    if route.description:
        kwargs['description'] = route.description
    if route.response_model is not None:
        kwargs['response_model'] = route.response_model
    if route.status_code is not None:
        kwargs['status_code'] = route.status_code
    if route.tags:
        kwargs['tags'] = list(route.tags)
    # ``extra`` holds framework-specific passthrough such as ``openapi_extra``
    # or ``dependencies`` — adapters merge it directly into add_api_route().
    kwargs.update(route.extra)

    endpoint = route.handler
    if route.rate_limit and limiter is not None:
        endpoint = _apply_rate_limit(endpoint, route.rate_limit, limiter)

    router.add_api_route(
        path=route.path,
        endpoint=endpoint,
        methods=list(route.methods),
        **kwargs,
    )


def _apply_rate_limit(
    handler: Callable[..., Any], limit_value: str, limiter: Any
) -> Callable[..., Any]:
    """Wrap ``handler`` so slowapi can enforce ``limit_value``.

    slowapi's ``@limiter.limit`` requires the endpoint to take ``request:
    Request`` so it can locate the request object. Controller methods don't
    declare it — so we synthesise a wrapper that does, FastAPI then injects
    the real ``Request`` by signature inspection, and the original handler
    keeps its clean signature.
    """
    sig = inspect.signature(handler)
    has_request = any(p.name == 'request' for p in sig.parameters.values())

    if has_request:
        # Handler already wants the request — just decorate directly.
        return limiter.limit(limit_value)(handler)

    new_params = [
        inspect.Parameter(
            'request', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        ),
        *sig.parameters.values(),
    ]
    new_sig = sig.replace(parameters=new_params)

    if asyncio.iscoroutinefunction(handler):
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop('request', None)
            return await handler(*args, **kwargs)
    else:
        def wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            kwargs.pop('request', None)
            return handler(*args, **kwargs)

    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    wrapper.__name__ = getattr(handler, '__name__', 'rate_limited_endpoint')
    wrapper.__qualname__ = getattr(handler, '__qualname__', wrapper.__name__)
    wrapper.__module__ = getattr(handler, '__module__', __name__)
    return limiter.limit(limit_value)(wrapper)


def _wrap_websocket_handler(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Adapt a ``WebSocketSession``-based handler into a Starlette endpoint.

    FastAPI injects the raw ``WebSocket`` by type annotation; we wrap it in a
    :class:`FastAPIWebSocketSession` so the business handler stays
    framework-agnostic.

    We deliberately avoid ``functools.wraps`` here: it sets ``__wrapped__``,
    which makes FastAPI's ``inspect.signature`` follow through to the business
    handler's ``WebSocketSession`` annotation and fail to build a dependant.
    """

    async def endpoint(websocket: WebSocket) -> None:
        await handler(FastAPIWebSocketSession(websocket))

    return endpoint


def _add_websocket_route(router: APIRouter, ws: WebSocketRoute) -> None:
    kwargs: dict[str, Any] = {}
    if ws.name:
        kwargs["name"] = ws.name
    kwargs.update(ws.extra)
    router.add_api_websocket_route(
        path=ws.path,
        endpoint=_wrap_websocket_handler(ws.handler),
        **kwargs,
    )
