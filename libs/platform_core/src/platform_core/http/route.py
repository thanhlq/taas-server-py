"""Framework-agnostic route metadata.

A :class:`Route` is a plain description of an HTTP endpoint. Adapters in
``http_fastapi``/``http_litestar`` translate it into the equivalent
framework primitive at registration time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from typing_extensions import Literal, TypeAlias

HttpMethod: TypeAlias = Literal[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD",
]


@dataclass
class Route:
    path: str
    methods: tuple[HttpMethod, ...]
    handler: Callable[..., Any]
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    response_model: Any = None
    status_code: int | None = None
    tags: tuple[str, ...] | None = None
    permissions: tuple[str, ...] | None = None
    middleware: tuple[Any, ...] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def with_handler(self, handler: Callable[..., Any]) -> Route:
        """Return a copy of this route with the handler replaced.

        Used when a controller binds an unbound method to its instance.
        """
        return Route(
            path=self.path,
            methods=self.methods,
            handler=handler,
            name=self.name,
            summary=self.summary,
            description=self.description,
            response_model=self.response_model,
            status_code=self.status_code,
            tags=self.tags,
            permissions=self.permissions,
            middleware=self.middleware,
            extra=dict(self.extra),
        )
