import logging
from logging import Logger
from typing import TYPE_CHECKING, Any, Optional

from platform_core.http import AppConfig
from platform_core.utils.singleton import singleton

from .config import (
    is_elk_tracing_enabled,
    is_otel_tracing_enabled,
    is_tracing_enabled,
)
from .defaults import NoopContextTracer
from .types import IContextTracer, ITracingManager

if TYPE_CHECKING:
    from platform_core.observability.types import InstrumentSettings


@singleton
class TracingFactory:
    _tracing_manager: Optional[ITracingManager] = None
    _logger: Optional[Logger] = None

    @property
    def logger(self) -> Logger:
        if not self._logger:
            self._logger = logging.getLogger('TracingFactory')
        return self._logger

    def get_tracing_manager(self) -> Optional[ITracingManager]:
        if not self._tracing_manager:
            from .factory import TracingManager
            self._tracing_manager = TracingManager(self.logger)
        return self._tracing_manager

    def initialize(self, app_settings: AppConfig) -> None:
        _ins_config: 'InstrumentSettings' = app_settings.instrumentation # type: ignore
        if _ins_config.logger:
            self._logger = _ins_config.logger

        if not is_tracing_enabled():
            self.logger.info('Tracing is not enabled.')

        if _ins_config.fastapi_app:
            self.trace_fastapi_app(_ins_config.fastapi_app)

        if _ins_config.aiokafka_instrument:
            self.trace_aiokafka(
                a_producer_hook=_ins_config.aiokafka_producer_hook,
                a_consumer_hook=_ins_config.aiokafka_consumer_hook,
            )

        self._tracing_manager = _ins_config.tracing_manager_class(self.logger)  if _ins_config.tracing_manager_class else self.get_tracing_manager()
        self.__initialized = True
        self.logger.info('TracingFactory initialized with manager: %s', type(self._tracing_manager).__name__)

    def get_context_tracer(self) -> type[IContextTracer]:
        if is_elk_tracing_enabled() or is_otel_tracing_enabled():
            if not self._tracing_manager:
                raise ValueError('TracingManager is not initialized.')

            return self._tracing_manager.get_context_tracer()
        else:
            return NoopContextTracer

    def trace_fastapi_app(self, fastapi_app: Any) -> None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(fastapi_app)
        self.logger.info('🔭 FastAPI Instrumented with OpenTelemetry configured')

    def trace_aiokafka(self, a_producer_hook, a_consumer_hook) -> None:
        if is_otel_tracing_enabled():
            from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor

            AIOKafkaInstrumentor().instrument(
                async_produce_hook=a_producer_hook, async_consume_hook=a_consumer_hook
            )
            self.logger.info('🔭 AIOKafka Instrumented with OpenTelemetry configured')

        elif is_elk_tracing_enabled():
            pass
