"""Decorators that mark methods as HTTP route handlers.

Each decorator attaches a :class:`Route` to the wrapped function via the
``__platform_core_route__`` attribute. A :class:`Controller` later collects
these and exposes them through :meth:`Controller.get_routes`.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from platform_core.http.route import HttpMethod, Route

ROUTE_ATTR = "__platform_core_route__"


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
