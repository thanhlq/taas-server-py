"""Register :class:`platform_core.http.Controller` instances with FastAPI."""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_args, get_origin, get_type_hints

from fastapi import APIRouter, Depends, FastAPI
from platform_core.db.advanced_session_manager import DBConcurrentSessionFactory
from platform_core.http import BaseController, Route, WebSocketRoute
from platform_core.http.cache import RequestLike, ResponseLike
from platform_core.http.context import Context
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket

from http_fastapi.adapters._websocket import FastAPIWebSocketSession
from http_fastapi.fastapi_msgspec.routing import MsgSpecRoute
from http_fastapi.middewares.request_context import get_request_context


def _is_db_injected_type(annotation: Any) -> bool:
    if annotation is inspect.Parameter.empty:
        return False
    if isinstance(annotation, str):
        return 'AsyncSession' in annotation or 'DBConcurrentSessionFactory' in annotation
    if hasattr(annotation, '__metadata__'):
        annotation = get_args(annotation)[0]
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is AsyncSession or annotation is DBConcurrentSessionFactory:
        return True
    if origin is None:
        return False
    return AsyncSession in args or DBConcurrentSessionFactory in args


def _route_specificity_key(path: str) -> tuple[int, ...]:
    """Rank a path by segment specificity (static beats path-param).

    Each path segment contributes ``0`` if it is a literal segment and ``1``
    if it is a path parameter (``{...}``). Sorting routes by this key
    registers more specific routes first, so a literal path like ``/error``
    is matched before a parametrised one like ``/{id}``.
    """
    segments = [seg for seg in path.strip('/').split('/') if seg]
    return tuple(1 if seg.startswith('{') and seg.endswith('}') else 0 for seg in segments)


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
    # Starlette matches routes in registration order, so a parametrised path
    # (``/{id}``) declared before a literal one (``/error``) would shadow it.
    # Register more specific (static-segment) routes first to mirror
    # Litestar's specificity-based matching.
    for r in sorted(controller.get_routes(), key=lambda route: _route_specificity_key(route.path)):
        _add_route(router, r, limiter)
    for ws in controller.get_websocket_routes():
        _add_websocket_route(router, ws)
    return router


def include_controller(
    app: FastAPI,
    controller: BaseController,
    **router_kwargs: Any,
) -> APIRouter:
    """
    Build a router for ``controller`` and attach it to ``app``.
    Examples:
    - Registering a controller with default settings:

    ```python
    include_controller(app, MyController())
    ```
    """
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

    endpoint = _retarget_cache_injected_params(endpoint)

    router.add_api_route(
        path=route.path,
        endpoint=endpoint,
        methods=list(route.methods),
        **kwargs,
    )


def _retarget_cache_injected_params(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Rewrite ``RequestLike``/``ResponseLike`` annotations on a handler.

    The framework-agnostic ``@cache`` decorator injects extra keyword-only
    parameters typed as ``RequestLike`` / ``ResponseLike`` (``Protocol``\\s)
    when the wrapped endpoint doesn't already declare ``request`` /
    ``response``. FastAPI can't build a dependant from a ``Protocol``
    annotation, so we substitute the concrete Starlette types here. The
    handler still receives the same objects under the same parameter names
    — only the public signature is updated.
    """
    sig = inspect.signature(handler)
    try:
        hints = get_type_hints(handler, include_extras=True)
    except Exception:
        hints = getattr(handler, '__annotations__', {}) or {}
    params = list(sig.parameters.values())
    # ``@functools.wraps`` (used by slowapi_advanced and others) sets
    # ``__wrapped__`` on the wrapper, which causes ``inspect.signature`` to
    # follow through to the underlying function — re-introducing ``self``
    # even when the caller passed us a bound method. Strip it explicitly.
    strip_self = bool(params) and params[0].name == 'self'
    if strip_self:
        params = params[1:]
    new_params: list[inspect.Parameter] = []
    changed = strip_self
    for p in params:
        hint = hints.get(p.name, p.annotation)
        if p.annotation is RequestLike:
            new_params.append(p.replace(annotation=Request))
            changed = True
        elif p.annotation is ResponseLike:
            new_params.append(p.replace(annotation=Response))
            changed = True
        elif _is_db_injected_type(hint):
            changed = True
            continue
        elif hint is Context and p.default is inspect.Parameter.empty:
            new_params.append(
                p.replace(annotation=Context, default=Depends(get_request_context))
            )
            changed = True
        else:
            if hint is not inspect.Parameter.empty and hint is not p.annotation:
                new_params.append(p.replace(annotation=hint))
                changed = True
            else:
                new_params.append(p)
    if not changed:
        return handler
    return_annotation = hints.get('return', sig.return_annotation)
    if return_annotation is type(None):
        # Keep the original ``-> None`` annotation shape so FastAPI's
        # 204 no-body checks continue to behave as expected.
        return_annotation = sig.return_annotation
    new_sig = sig.replace(parameters=new_params, return_annotation=return_annotation)

    # Wrap in a fresh function so we can attach ``__signature__`` without
    # mutating the underlying ``__func__`` (which would re-introduce
    # ``self`` on every other call site).
    if inspect.iscoroutinefunction(handler):
        async def cache_wrapped_async(*args: Any, **kwargs: Any) -> Any:
            return await handler(*args, **kwargs)
        wrapped = cache_wrapped_async
    else:
        def cache_wrapped_sync(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            return handler(*args, **kwargs)
        wrapped = cache_wrapped_sync

    wrapped.__name__ = getattr(handler, '__name__', 'cache_endpoint')
    wrapped.__qualname__ = getattr(handler, '__qualname__', wrapped.__name__)
    wrapped.__module__ = getattr(handler, '__module__', __name__)
    wrapped.__doc__ = getattr(handler, '__doc__', None)
    wrapped.__annotations__ = {
        k: (
            sig.return_annotation
            if k == 'return' and v is type(None)
            else v
        )
        for k, v in hints.items()
        if v is not inspect.Parameter.empty
    }
    from typing import cast as _cast
    _cast(Any, wrapped).__signature__ = new_sig
    return wrapped


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

    if inspect.iscoroutinefunction(handler):
        async def rate_limited_wrapper_async(*args: Any, **kwargs: Any) -> Any:
            kwargs.pop('request', None)
            return await handler(*args, **kwargs)
        rate_limited_wrapper = rate_limited_wrapper_async
    else:
        def rate_limited_wrapper_sync(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            kwargs.pop('request', None)
            return handler(*args, **kwargs)
        rate_limited_wrapper = rate_limited_wrapper_sync

    from typing import cast as _cast
    _cast(Any, rate_limited_wrapper).__signature__ = new_sig
    rate_limited_wrapper.__name__ = getattr(handler, '__name__', 'rate_limited_endpoint')
    rate_limited_wrapper.__qualname__ = getattr(
        handler, '__qualname__', rate_limited_wrapper.__name__
    )
    rate_limited_wrapper.__module__ = getattr(handler, '__module__', __name__)
    return limiter.limit(limit_value)(rate_limited_wrapper)


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
