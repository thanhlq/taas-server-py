"""
Load the logging/tracing/... implementation
"""

import logging
from logging import Logger
from typing import TYPE_CHECKING, Optional

from foundation.config.log import LogSettings
from foundation.observability.base_logger import ROOT_LOGGER_NAME
from foundation.observability.types import Logging
from foundation.utils.singleton import singleton

if TYPE_CHECKING:
    from foundation.config.settings import Settings

from .config import (
    is_otel_tracing_enabled,
)

if is_otel_tracing_enabled():
    from .opentelemetry import (
        OtelLogAdapter as LogAdapter,
    )
    from .opentelemetry import (
        OtelTracingManager as TracingManager,
    )
    from .opentelemetry import (
        instrument,
    )

else:
    from .base_logger import DefaultLogAdapter as LogAdapter
    from .defaults import NoopTracingManager as TracingManager
    from .defaults import noop_instrument as instrument


DISABLE_DEBUG_IN_LOGGER = [
    'urllib3.connectionpool',
    'urllib3.util.retry',
    'passlib.utils.compat',
    'aiokafka',
    'aiokafka.conn',
    'aiokafka.consumer.consumer',
    'passlib.registry',
    'httpcore.http11',
    'httpcore.connection',
]


@singleton
class LogFactory:
    _root_logger: Logger
    _adapter: LogAdapter
    _settings: 'Settings'

    def __init__(self):
        from foundation.config import get_settings

        self._settings = get_settings()
        self._validate_config()

        # Initialize the root logger with the configured handlers and log level
        handlers = self.get_configured_handlers()
        logging.basicConfig(
            handlers=handlers, level=self.settings.LOG_LEVEL
        )
        for logger_name in DISABLE_DEBUG_IN_LOGGER:
            logging.getLogger(logger_name).setLevel(logging.WARNING)

        self.logger.info(
            '📝 Initializing logging with adapter [%s] log level: %s, handlers: %s', self._adapter.__class__.__name__, self.settings.LOG_LEVEL, handlers
        )

    @property
    def settings(self) -> LogSettings:
        """Configure the logging system by patching logging.getLogger."""
        return self._settings.log

    @property
    def log_adapter(self) -> LogAdapter:
        if not hasattr(self, '_adapter'):
            self._adapter = LogAdapter()
        return self._adapter

    @property
    def logger(self) -> Logger:
        if not hasattr(self, '_root_logger'):
            self._root_logger = self.get_logger(ROOT_LOGGER_NAME)
        return self._root_logger

    def get_configured_handlers(self) -> list[logging.Handler]:
        """Return all handlers configured for the root logger, including those from the adapter and any additional handlers."""
        return self.logger.handlers

    def is_debug_enabled(self) -> bool:
        from foundation.config import get_settings

        settings = get_settings()
        return settings.is_debug()

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        if name:
            return self.log_adapter.create_logger(name)
        return self.logger

    def _validate_config(self) -> None:
        settings = self._settings
        log_providers = settings.log.LOG_ADAPTERS if settings.log.LOG_ADAPTERS else ''

        if not log_providers:
            self._disabled_logging = True
            return

        supported_providers = {
            Logging.LOG_ADAPTER_CONSOLE,
            Logging.LOG_ADAPTER_FILE,
            Logging.LOG_ADAPTER_ELK,
            Logging.LOG_ADAPTER_OTLP_HTTP,
            Logging.LOG_ADAPTER_OTLP_GRPC,
        }

        for provider in log_providers.split(','):
            if provider not in supported_providers:
                raise ValueError(f'📝 Unsupported log adapter: {provider}')

        if Logging.LOG_ADAPTER_ELK in log_providers and 'otlp' in log_providers:
            raise ValueError('ELK and OTEL log adapters cannot be used together.')


logger: Logger = LogFactory().logger
""" Default logger instance that can be imported and used across the application. """

__all__ = ['instrument', 'LogAdapter', 'TracingManager', 'logger']
