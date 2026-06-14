from typing import Optional

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from ....core.src.core.common.base_logger import DefaultLogAdapter
from ....core.src.core.common.types import ILogAdapter
from ....core.src.core.observability.noop_context_tracer import NoopContextTracer
from .config import (
    is_elk_tracing_enabled,
    is_otel_tracing_enabled,
    is_tracing_enabled,
)
from .types import ApplicationContext, IContextTracer, ITracingManager

# def is_elk_tracing_enabled() -> bool:
#     settings: AppSetting = get_app_settings()
#     return Tracing.TRACING_ADAPTER_ELK in settings.TRACING_ADAPTERS


# def is_otel_tracing_enabled() -> bool:
#     settings: AppSetting = get_app_settings()
#     return (
#         Tracing.TRACING_ADAPTER_OTLP_HTTP in settings.TRACING_ADAPTERS
#         or Tracing.TRACING_ADAPTER_OTLP_GRPC in settings.TRACING_ADAPTERS
#     )


# def is_tracing_enabled() -> bool:
#     return is_elk_tracing_enabled() or is_otel_tracing_enabled()


class TracingFactory:
    _instance: Optional['TracingFactory'] = None
    _tracing_manager: Optional[ITracingManager] = None
    _logger: Optional[ILogAdapter] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__()
            self._logger = None
            self._initialized = True

    @property
    def logger(self) -> ILogAdapter:
        if not self._logger:
            self._logger = DefaultLogAdapter()
        return self._logger

    def get_tracing_manager(self) -> Optional[ITracingManager]:
        return self._tracing_manager

    def initialize(self, params: ApplicationContext) -> None:
        if not is_tracing_enabled():
            if params.startupOptions.logger:
                params.startupOptions.logger.info('Tracing is not enabled.')
            return

        if TracingFactory._instance is not None:
            if params.startupOptions.logger:
                params.startupOptions.logger.info('Tracing is already initialized.')
            return

        self._logger = params.startupOptions.logger

        if params.startupOptions.fastapi_app:
            self.trace_fastapi_app(params.startupOptions.fastapi_app)

        # settings = get_app_settings()
        # if (
        #     settings.PUBSUB_SERVICE_PROVIDER
        #     and 'kafka' in settings.PUBSUB_SERVICE_PROVIDER
        # ):
        #     TracingFactory().trace_aiokafka(
        #         a_producer_hook=params.aiokafka_producer_hook,
        #         a_consumer_hook=params.aiokafka_consumer_hook,
        #     )
        if params.startupOptions.aiokafka_instrument:
            self.trace_aiokafka(
                a_producer_hook=params.startupOptions.aiokafka_producer_hook,
                a_consumer_hook=params.startupOptions.aiokafka_consumer_hook,
            )

        self._tracing_manager = params.startupOptions.tracing_manager_class(self.logger)  # type: ignore

        # if is_otel_tracing_enabled():
        #     from core.observability.otel.otel_tracing import OtelTracingManager

        #     # Initialize OtelTracingManager
        #     TracingFactory()._tracing_manager = OtelTracingManager()
        # elif is_elk_tracing_enabled():
        #     from core.observability.elk.elk_tracing import ElkTracingManager

        #     # Initialize ElkTracingManager
        #     TracingFactory()._tracing_manager = ElkTracingManager()

    def get_context_tracer(self) -> type[IContextTracer]:
        if is_elk_tracing_enabled() or is_otel_tracing_enabled():
            if not self._tracing_manager:
                raise ValueError('TracingManager is not initialized.')

            return self._tracing_manager.get_context_tracer()
        else:
            return NoopContextTracer

    def trace_fastapi_app(self, appContext: ApplicationContext):
        FastAPIInstrumentor.instrument_app(appContext.startupOptions.fastapi_app)
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

    # @staticmethod
    # def trace_faust_app(appContext: ApplicationContext):
    #     from faust import App as FaustApp

    #     if is_otel_tracing_enabled():
    #         from .otel.otel_tracing import OtelTracingManager

    #         faust_app = cast(FaustApp, app)
    #         faust_app.sensors.add(OtelTracingManager().get_faust_sensor())

    #     if is_elk_tracing_enabled():
    #         from .elk.elk_tracing import ElkTracingManager

    #         faust_app = cast(FaustApp, app)
    #         faust_app.sensors.add(ElkTracingManager().get_faust_sensor())

    #     return app


