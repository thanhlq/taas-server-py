"""
Load the logging/tracing/... implementation
"""
import logging
from logging import Logger
from typing import TYPE_CHECKING, Optional

from platform_core.observability.base_logger import ROOT_LOGGER_NAME
from platform_core.observability.types import Logging
from platform_core.utils.singleton import singleton

if TYPE_CHECKING:
    from platform_core.config.settings import Settings

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


@singleton
class LogFactory:
    _root_logger: Logger
    _adapter: LogAdapter
    _settings: 'Settings'

    def __init__(self) -> None:
        from platform_core.config import get_settings
        self._settings = get_settings()
        self._validate_config()

    @property
    def log_adapter(self) -> LogAdapter:
        if not hasattr(self, '_adapter'):
            self._adapter = LogAdapter()
        return self._adapter

    @property
    def logger(self) -> Logger:
        if not hasattr(self, '_root_logger'):
            self._root_logger = Logger(ROOT_LOGGER_NAME)
        return self._root_logger

    def is_debug_enabled(self) -> bool:
        from platform_core.config import get_settings
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


__all__ = ['instrument', 'LogAdapter', 'TracingManager']
