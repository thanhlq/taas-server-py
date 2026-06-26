"""
🔍 OpenTelemetry Tracing Setup

Initializes the OpenTelemetry tracer provider and configures exporters
based on application settings from Pydantic configuration.

Author: Thanh Le
"""
from logging import Logger
from typing import Optional

from opentelemetry import trace
from opentelemetry.context.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as OTLPGrpcSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as OTLPHttpSpanExporter,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# from opentracing import Span
from opentelemetry.trace.span import Span

from platform_core.observability.base_logger import DefaultLogAdapter
from platform_core.utils.singleton import singleton

from ..types import (
    IContextTracer,
    ITracingManager,
)
from .otel_config import (
    OtelConfig,
)


@singleton
class OtelTracingManager(ITracingManager):
    """[SINGLETON] A class for initialize of OpenTelemetry tracing."""

    _instance: Optional['OtelTracingManager'] = None
    trace_provider: TracerProvider
    config: OtelConfig
    default_tracer: Optional[trace.Tracer] = None
    _logger: Optional[Logger] = None

    def __init__(self, logger: Optional[Logger] = None):
        super().__init__(logger)
        self.config = OtelConfig()
        # self.default_tracer = None  # Initialize before conditional use
        if self.config.is_tracing_enabled():
            self.trace_provider = self.init_tracer_provider()
            trace.set_tracer_provider(self.trace_provider)
            self.default_tracer = self.get_tracer()
            self.test_tracing()
        else:
            self.logger.debug('⚫ OpenTelemetry tracing is not enabled but initialized.')
        self._logger = logger
        self.logger.info('OtelTracingManager initialized with config: %s', self.config)

    @property
    def logger(self) -> Logger:
        if not self._logger:
            self._logger = DefaultLogAdapter().create_logger('OtelTracingManager')
        return self._logger

    def get_context_tracer(self) -> type[IContextTracer]:
        return OtelContextTracer

    def capture_exception(self, e: Exception):
        try:
            span = self.get_current_span()
            span.record_exception(e)
            if span.is_recording():
                span.set_status(Status(StatusCode.ERROR))
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f'⚠️ Failed to capture exception in span: {str(e)}', exc_info=True
                )
            else:
                print(f'⚠️ Failed to capture exception in span: {e}')

    def get_carrier(self) -> dict[str, str]:
        carrier = {}
        TraceContextTextMapPropagator().inject(carrier)
        return carrier

    def get_propagated_aiokafka_headers(self) -> list[tuple[str, bytes]]:
        carrier = {}
        TraceContextTextMapPropagator().inject(carrier)
        # Convert carrier dict to Kafka headers format [(key, value_bytes), ...]
        headers = [(key, value.encode('utf-8')) for key, value in carrier.items()]
        return headers

    def int_to_hex(self, value: int) -> str:
        return format(value, '032x')

    def get_current_trace_id(self) -> Optional[str]:
        span = self.get_current_span()
        trace_id = span.get_span_context().trace_id
        return self.int_to_hex(trace_id)

    def get_current_span(self) -> Span:
        return trace.get_current_span()

    def get_current_span_id(self) -> Optional[str]:
        span = self.get_current_span()
        span_id = span.get_span_context().span_id
        return self.int_to_hex(span_id)

    def init_tracer_provider(self):
        config: OtelConfig = self.config
        resource = Resource(
            attributes={
                SERVICE_NAME: config.service_name,
            }
        )
        provider = TracerProvider(resource=resource)

        if config.trace_exporter_protocol == 'grpc':
            otlp_exporter = OTLPGrpcSpanExporter(
                endpoint=config.trace_exporter_endpoint,
                insecure=config.trace_exporter_insecured,
            )
        else:
            otlp_exporter = OTLPHttpSpanExporter(
                endpoint=config.trace_exporter_endpoint,
                headers=config.build_basic_auth_headers(),
            )

        # Use shorter export intervals to reduce "root span not received" issues
        # Default is 5s max_export_batch_timeout and 30s schedule_delay
        provider.add_span_processor(
            BatchSpanProcessor(
                otlp_exporter,
                export_timeout_millis=2000,  # 2s timeout
                schedule_delay_millis=1000,  # Export every 1s
            )
        )

        if config.is_tracing_console_enabled():
            # Normally used for debugging
            console_exporter = ConsoleSpanExporter()
            provider.add_span_processor(
                BatchSpanProcessor(
                    console_exporter,
                    schedule_delay_millis=1000,
                )
            )

        return provider

    def get_tracer(self, name: Optional[str] = None) -> trace.Tracer:
        if name is None or name == '':
            if not self.default_tracer:
                name = f'{self.config.service_name}'
                self.logger.info(f'🔭 Creating default tracer with name: {name}')
                self.default_tracer = trace.get_tracer(name)
            return self.default_tracer

        else:
            self.logger.info(f'🔭 Creating tracer with name: {name}')
            return trace.get_tracer(name)

    def get_faust_sensor(self):
        # from .otel_faust_sensor import OtelFaustSensor
        raise NotImplementedError('Faust sensor integration is not implemented yet.')

    def test_tracing(self):
        tracer = self.get_tracer()
        with tracer.start_as_current_span('🐍 Tracing enabled') as span:
            # span.set_attribute('attribute_key', 'attribute_value')
            # print('🔍 OpenTelemetry tracing is configured and working!')
            span.set_attribute('test_attribute', 'test_value')
            pass


class OtelContextTracer(IContextTracer):
    """
    A context manager for tracing code blocks with OpenTelemetry.

    Examples:
        with ContextTracer("my-span", traceparent) as span:
            # Your code here
            span.set_attribute("key", "value")
    """

    span: Optional[Span] = None

    def __init__(
        self,
        span_name: str,
        traceparent: Optional[str] = None,
        ctx: Optional[Context] = None,
    ):
        """
        Initialize the context tracer.

        Args:
            span_name: Name of the span to create
            traceparent: Optional W3C traceparent header for distributed tracing
        """
        self.span_name = span_name
        self.traceparent = traceparent
        self.span = None
        self.ctx: Optional[Context] = ctx
        self.span_context_man = None

    def __enter__(self) -> IContextTracer:
        """Enter the context manager and start the span."""
        tracer = OtelTracingManager().get_tracer()

        if self.ctx is not None:
            self.span_context_man = tracer.start_as_current_span(
                self.span_name, context=self.ctx
            )
        elif self.traceparent:
            carrier = {'traceparent': self.traceparent}
            self.ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
            self.span_context_man = tracer.start_as_current_span(
                self.span_name, context=self.ctx
            )
        else:
            self.span_context_man = tracer.start_as_current_span(
                self.span_name
            ).__enter__()
            # self.span = trace.get_current_span()
        self.span = self.span_context_man.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager and end the span."""
        # self.span_context_man.__exit__(exc_type, exc_val, exc_tb)
        if self.span_context_man:
            self.span_context_man.__exit__(exc_type, exc_val, exc_tb)

    def set_attribute(self, key, value):
        if self.span:
            return self.span.set_attribute(key, value)
        else:
            print('⚠️ Warning: Attempted to set attribute on a non-existent span.')

    def record_exception(self, e: Exception):
        if self.span:
            self.span.record_exception(e)
            self.span.set_status(Status(StatusCode.ERROR, str(e)))
        else:
            print('⚠️ Warning: Attempted to record exception on a non-existent span.')
        return self
