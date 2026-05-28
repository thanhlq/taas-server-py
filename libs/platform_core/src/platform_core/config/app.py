from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from platform_core.config.allowed_hosts import AllowedHostsConfig
from platform_core.datastructures import State
from platform_core.events.emitter import SimpleEventEmitter
from platform_core.types.composite_types import Middleware
from platform_core.types.empty import Empty

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from platform_core.config.compression import CompressionConfig
    from platform_core.config.cors import CORSConfig
    from platform_core.config.csrf import CSRFConfig
    from platform_core.config.ratelimit import RateLimitConfig
    from platform_core.config.wss import WebSocketConfig
    from platform_core.config.lock import DistributedLockConfig
    from platform_core.config.cache import CacheConfig
    from platform_core.config.log_config import BaseLoggingConfig
    from platform_core.events.emitter import BaseEventEmitterBackend
    from platform_core.events.listener import EventListener
    from platform_core.openapi.config import OpenAPIConfig
    from platform_core.openapi.spec import SecurityRequirement
    from platform_core.types.callable_types import LifespanHook
    from platform_core.types.composite_types import TypeDecodersSequence
    from platform_core.types.empty import EmptyType


__all__ = (
    'AppConfig',
    'ExperimentalFeatures',
)


@dataclass
class AppConfig:
    """The parameters provided to the ``Litestar`` app are used to instantiate an instance, and then the instance is
    passed to any callbacks registered to ``on_app_init`` in the order they are provided.

    The final attribute values are used to instantiate the application object.
    """

    compression_config: CompressionConfig | None = field(default=None)
    """Configures compression behaviour of the application, this enabled a builtin or user defined Compression
    middleware.
    """
    cors_config: CORSConfig | None = field(default=None)
    """If set this enables the builtin CORS middleware."""
    csrf_config: CSRFConfig | None = field(default=None)
    """If set this enables the builtin CSRF middleware."""
    ratelimit_config: RateLimitConfig | None = field(default=None)
    cache_config: CacheConfig | None = field(default=None)
    distributed_lock_config: DistributedLockConfig | None = field(default=None)
    websocket_config: WebSocketConfig | None = field(default=None)
    debug: bool = field(default=False)
    """If ``True``, app errors rendered as HTML with a stack trace."""
    event_emitter_backend: type[BaseEventEmitterBackend] = field(
        default=SimpleEventEmitter
    )
    """A subclass of :class:`BaseEventEmitterBackend <.events.emitter.BaseEventEmitterBackend>`."""
    include_in_schema: bool | EmptyType = field(default=Empty)
    """A boolean flag dictating whether  the route handler should be documented in the OpenAPI schema"""
    """A list of callables returning async context managers, wrapping the lifespan of the ASGI application"""
    listeners: list[EventListener] = field(default_factory=list)
    """A list of :class:`EventListener <.events.listener.EventListener>`."""
    logging_config: BaseLoggingConfig | None = field(default=None)
    """An instance of :class:`BaseLoggingConfig <.logging.config.BaseLoggingConfig>` subclass."""
    middleware: list[Middleware] = field(default_factory=list)
    """A list of :class:`Middleware <.types.Middleware>`."""
    on_shutdown: list[LifespanHook] = field(default_factory=list)
    """A list of :class:`LifespanHook <.types.LifespanHook>` called during application shutdown."""
    on_startup: list[LifespanHook] = field(default_factory=list)
    """A list of :class:`LifespanHook <.types.LifespanHook>` called during application startup."""
    openapi_config: OpenAPIConfig | None = field(default=None)
    """Defaults to :data:`DEFAULT_OPENAPI_CONFIG <platform_core.app.DEFAULT_OPENAPI_CONFIG>`"""
    opt: dict[str, Any] = field(default_factory=dict)
    """A string keyed dictionary of arbitrary values that can be accessed in :class:`Guards <.types.Guard>` or
    wherever you have access to :class:`Request <.connection.Request>` or :class:`ASGI Scope <platform_core.types.Scope>`.

    Can be overridden by routers and router handlers.
    """
    """A mapping of :class:`Parameter <.params.Parameter>` definitions available to all application paths."""
    path: str = field(default='')
    """A base path that prefixed to all route handlers, controllers and routers associated with the
    application instance.

    .. versionadded:: 2.8.0
    """
    pdb_on_exception: bool = field(default=False)
    """Drop into the PDB on an exception"""
    """A `pdb`-like debugger module that supports the `post_mortem()` protocol.
    This module will be used when `pdb_on_exception` is set to True."""
    request_max_body_size: int | None | EmptyType = Empty
    """Maximum allowed size of the request body in bytes. If this size is exceeded, a '413 - Request Entity Too Large'
    error response is returned."""
    """Configures caching behavior of the application."""
    security: list[SecurityRequirement] = field(default_factory=list)
    """A list of dictionaries that will be added to the schema of all route handlers in the application. See
    :data:`SecurityRequirement <.openapi.spec.SecurityRequirement>` for details.
    """
    signature_namespace: dict[str, Any] = field(default_factory=dict)
    """A mapping of names to types for use in forward reference resolution during signature modelling."""
    signature_types: list[Any] = field(default_factory=list)
    """A sequence of types for use in forward reference resolution during signature modelling.

    These types will be added to the signature namespace using their ``__name__`` attribute.
    """
    state: State = field(default_factory=State)
    """A :class:`State` <.datastructures.State>` instance holding application state."""
    tags: list[str] = field(default_factory=list)
    """A list of string tags that will be appended to the schema of all route handlers under the application."""

    allowed_hosts: AllowedHostsConfig | list[str] | None = field(default=None)

    def __post_init__(self) -> None:
        """Normalize the allowed hosts to be a config or None.

        Returns:
            Optional config.
        """
        if self.allowed_hosts and isinstance(self.allowed_hosts, list):
            self.allowed_hosts = AllowedHostsConfig(allowed_hosts=self.allowed_hosts)


class ExperimentalFeatures(str, enum.Enum):
    DTO_CODEGEN = 'DTO_CODEGEN'
    """Enable DTO codegen."""
    FUTURE = 'FUTURE'
    """Enable future features that may be considered breaking or changing."""
