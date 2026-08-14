from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from starlette.responses import Response

from foundation.config.allowed_hosts import AllowedHostsConfig
from foundation.datastructures import State
from foundation.events.emitter import SimpleEventEmitter
from foundation.observability.types import ServiceInstrumentConfig
from foundation.types.composite_types import Middleware
from foundation.types.empty import Empty

if TYPE_CHECKING:

    from foundation.config.cache import CacheConfig
    from foundation.config.compression import CompressionConfig
    from foundation.config.cors import CORSConfig
    from foundation.config.csrf import CSRFConfig
    from foundation.config.lock import DistributedLockConfig
    from foundation.config.log_config_todo import BaseLoggingConfig
    from foundation.config.ratelimit import RateLimitConfig
    from foundation.config.wss import WebSocketConfig
    from foundation.events.emitter import BaseEventEmitterBackend
    from foundation.events.listener import EventListener
    from foundation.openapi.config import OpenAPIConfig
    from foundation.openapi.spec import SecurityRequirement
    from foundation.types.callable_types import LifespanHook
    from foundation.types.empty import EmptyType


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

    name: str | None = field(default=None)
    debug: bool = field(default=False)

    instrumentation: ServiceInstrumentConfig | None = field(default=None)
    """The configuration for observability instrumentation. If provided,
    the app will be automatically instrumented according to the settings. If not provided, no instrumentation will be applied."""

    # Serialization:
    default_response_class: type[Response] | None = field(default=None)
    """The default response class to use for route handlers that don't explicitly set one."""

    deploy_env: str | None = field(default='development')
    """The environment the app is being deployed in, e.g. "production", "staging", "development".
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
    openapi_enabled: bool = field(default=True)
    """A boolean flag dictating whether or not to generate and serve an OpenAPI schema."""
    openapi_config: OpenAPIConfig | None = field(default=None)
    """Defaults to :data:`DEFAULT_OPENAPI_CONFIG <foundation.app.DEFAULT_OPENAPI_CONFIG>`"""
    opt: dict[str, Any] = field(default_factory=dict)
    """A string keyed dictionary of arbitrary values that can be accessed in :class:`Guards <.types.Guard>` or
    wherever you have access to :class:`Request <.connection.Request>` or :class:`ASGI Scope <foundation.types.Scope>`.

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
    # """ csrf_config: CSRFConfig | None = field(default=None) """

    def get_instrumentation_settings(self) -> ServiceInstrumentConfig:
        """Return the instrumentation settings for the application.

        Returns:
            The instrumentation settings.
        """
        if not self.instrumentation:
            self.instrumentation = ServiceInstrumentConfig()
        return self.instrumentation

    def __post_init__(self) -> None:
        """Normalize the allowed hosts to be a config or None.

        Returns:
            Optional config.
        """
        if self.allowed_hosts and isinstance(self.allowed_hosts, list):
            self.allowed_hosts = AllowedHostsConfig(allowed_hosts=self.allowed_hosts)


class ExperimentalFeatures(StrEnum):
    DTO_CODEGEN = 'DTO_CODEGEN'
    """Enable DTO codegen."""
    FUTURE = 'FUTURE'
    """Enable future features that may be considered breaking or changing."""
