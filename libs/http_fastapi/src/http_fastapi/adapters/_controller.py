"""Register :class:`platform_core.http.Controller` instances with FastAPI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from platform_core.http import BaseController, Route

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
    **router_kwargs: Any,
) -> APIRouter:
    """Build an :class:`APIRouter` populated with the controller's routes."""
    router = APIRouter(**_router_kwargs(controller, router_kwargs))
    for r in controller.get_routes():
        _add_route(router, r)
    return router


def include_controller(
    app: FastAPI,
    controller: BaseController,
    **router_kwargs: Any,
) -> APIRouter:
    """Build a router for ``controller`` and attach it to ``app``."""
    router = build_router_for_controller(controller, **router_kwargs)
    app.include_router(router)
    return router


def _add_route(router: APIRouter, route: Route) -> None:
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
    router.add_api_route(
        path=route.path,
        endpoint=route.handler,
        methods=list(route.methods),
        **kwargs,
    )
