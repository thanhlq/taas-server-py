from abc import ABC, abstractmethod
from dataclasses import dataclass
from logging import Logger
from typing import Any, Callable, Optional, Union


class Logging:
    """Logging adapter types and configuration constants."""

    LOG_FORMAT_STANDARD = 'standard'
    LOG_FORMAT_DETAILED = 'detailed'
    LOG_FORMAT_JSON = 'json'

    LOG_ADAPTER_CONSOLE = 'console'
    """Console logging adapter (stdout/stderr)"""

    LOG_ADAPTER_FILE = 'file'
    """File-based logging adapter"""

    LOG_ADAPTER_OTLP_HTTP = 'otlp-http'
    """OpenTelemetry Protocol HTTP logging adapter"""

    LOG_ADAPTER_OTLP_GRPC = 'otlp-grpc'
    """OpenTelemetry Protocol gRPC logging adapter"""

    LOG_ADAPTER_ELK = 'elk'

    LOG_OTEL_HTTP_ENDPOINT_DEFAULT = 'http://localhost:4318/v1/logs'
    """Default HTTP endpoint for OpenTelemetry logs"""

    LOG_OTEL_GRPC_ENDPOINT_DEFAULT = 'http://localhost:4317'
    """Default gRPC endpoint for OpenTelemetry logs"""


# ═══════════════════════════════════════════════════════════════════════════════
# 📊 TRACING CONFIGURATION CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
"""
Distributed tracing configuration constants for different adapters and endpoints.
These define the available tracing backends and their default configurations.
"""


class Tracing:
    """Tracing adapter types and configuration constants."""

    DEFAULT_TRACER_NAME = 'main'
    """Default tracer name for the application"""

    TRACING_ADAPTER_CONSOLE = 'console'
    """Console tracing adapter (stdout for debugging)"""

    TRACING_ADAPTER_ELK = 'elk'
    """Elastic tracing adapter"""

    TRACING_ADAPTER_OTLP_HTTP = 'otlp-http'
    """OpenTelemetry Protocol HTTP tracing adapter"""

    TRACING_ADAPTER_OTLP_GRPC = 'otlp-grpc'
    """OpenTelemetry Protocol gRPC tracing adapter"""

    TRACING_OTEL_HTTP_ENDPOINT_DEFAULT = 'http://localhost:4318/v1/traces'
    """Default HTTP endpoint for OpenTelemetry traces"""

    TRACING_OTEL_GRPC_ENDPOINT_DEFAULT = 'http://localhost:4317'
    """Default gRPC endpoint for OpenTelemetry traces"""


@dataclass
class O11yGlobalAppConfiguration:
    """
    Contain the configuration for a service or applications i.e. what should be traced, what should be logged, etc.
    """

    """
    Parameters for setting up the application context.
    """

    app_name: str
    # Logging
    logger_class: Optional[type[Logger]] = None
    uvicorn_log_config_builder: Optional[
        Union[dict[str, Any], Callable[[], dict[str, Any]]]
    ] = None
    # Tracing
    tracing_manager_class: Optional[type[ITracingManager]] = None
    instrument_decorator: Optional[Callable] = None
    fastapi_app: Optional[Any] = None
    aiokafka_instrument: bool = False
    aiokafka_producer_hook: Optional[Any] = None
    aiokafka_consumer_hook: Optional[Any] = None
    redis_instrument: bool = False
    sqlalchemy_instrument: bool = False

    logger: Optional[Logger] = None


class TracingContextT(ABC):
    """
    A global interface for tracing context.
    The implementation can be in Elastic APM, Open Telemetry, etc.
    """

    @abstractmethod
    def getLogger(self) -> Logger: ...

    """ Get the logger for the current tracing context. The logger should be configured to include tracing information in the logs."""


class LoggingFactoryT:
    """
    A global interface for logging context.
    The implementation can be in Elastic APM, Open Telemetry, etc.
    """


class ObservabilityT(ABC):
    """
    A global interface for specfic observability implementations.
    The implementation can be in Elastic APM, Open Telemetry, etc.
    """

    def __init__(
        self, tracing_context: TracingContextT, logging_factory: LoggingFactoryT
    ):
        self.tracing_context = tracing_context
        self.logging_factory = logging_factory


class IContextTracer(ABC):
    """Abstract async context tracer interface."""

    @abstractmethod
    def __init__(
        self, span_name: str, traceparent: Optional[str] = None, ctx: Any = None
    ): ...

    @abstractmethod
    def __enter__(self) -> 'IContextTracer': ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb): ...

    @abstractmethod
    def set_attribute(self, key: str, value: Any): ...

    @abstractmethod
    def record_exception(self, e: Exception) -> 'IContextTracer': ...

    # @abstractmethod
    # def set_status(self, status: Any) -> None: ...

    # @abstractmethod
    # def set_attributes(self, key: str, value: Any) -> None: ...
    # """ i.e. ct.set_attribute('retry_count', event.metadata.retry_count) """


class ITracingManager(ABC):
    """
    Interface for a Tracing Manager.

    Defines the contract for tracing implementations (OpenTelemetry, Jaeger, etc.)
    to provide distributed tracing capabilities across the application.
    """

    @abstractmethod
    def get_context_tracer(self) -> type[IContextTracer]:
        """
        Get the context tracer class.

        Returns:
            Class implementing IContextTracer for creating tracing spans.
        """
        ...

    @abstractmethod
    def get_tracer(self, name: Optional[str] = None) -> Any:
        """
        Get a tracer instance by name.

        Args:
            name: Optional name for the tracer. If None, returns the default tracer.

        Returns:
            Tracer instance for creating spans and tracing operations.
        """
        pass

    @abstractmethod
    def get_current_trace_id(self) -> Optional[str]:
        """
        Get the current trace ID in hexadecimal format.

        Returns:
            Hexadecimal string representation of the current trace ID,
            or None if no active span exists.
        """
        pass

    @abstractmethod
    def get_current_span(self) -> Any:
        """
        Get the current active span.

        Returns:
            Current span object, or None if no span is active.
        """
        pass

    @abstractmethod
    def get_current_span_id(self) -> Optional[str]:
        """
        Get the current span ID in hexadecimal format.

        Returns:
            Hexadecimal string representation of the current span ID,
            or None if no active span exists.
        """
        pass

    @abstractmethod
    def capture_exception(self, e: Exception):
        """
        Record an exception in the current span.

        Args:
            ex: Exception instance to record. If None, records the current exception.
        """
        pass

    @abstractmethod
    def get_propagated_aiokafka_headers(self) -> list[tuple[str, bytes]]:
        """
        Kafka headers to be included in the message using
                the format ``[("key", b"value")]``. Iterable of tuples where key
                is a normal string and value is a byte string.
        """
        pass

    @abstractmethod
    def get_faust_sensor(self) -> Any:
        """
        Get a Faust sensor for Kafka stream processing tracing.

        Returns:
            Faust sensor instance for monitoring Kafka streams.
        """
        pass

    @abstractmethod
    def get_carrier(self) -> dict[str, str]:
        """
        Get the tracing carrier for propagation.

        Returns:
            A dictionary representing the tracing carrier with keys like
            'traceparent', 'tracestate', and 'baggage'.
        """
        ...



@dataclass
class InstrumentSettings:
    """
    Parameters for setting up the application context.
    """

    logger_class: Optional[type[Logger]] = None
    uvicorn_log_config_builder: Optional[
        Union[dict[str, Any], Callable[[], dict[str, Any]]]
    ] = None
    logger: Optional[Logger] = None

    # Tracing
    tracing_manager_class: Optional[type[ITracingManager]] = None
    instrument_decorator: Optional[Callable] = None
    fastapi_app: Optional[Any] = None
    aiokafka_instrument: bool = False
    aiokafka_producer_hook: Optional[Any] = None
    aiokafka_consumer_hook: Optional[Any] = None
    redis_instrument: bool = False
    sqlalchemy_instrument: bool = False
