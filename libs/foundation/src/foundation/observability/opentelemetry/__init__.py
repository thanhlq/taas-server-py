from foundation.observability.types import ObservabilityT

from .decorator import instrument
from .otel_logging import OtelLogAdapter
from .otel_tracing import OtelTracingManager


class OpentelemetryObservability(ObservabilityT):
    """
    A global interface for specfic observability implementations.
    The implementation can be in Elastic APM, Open Telemetry, etc.
    """


__all__ = ['OtelLogAdapter', 'OtelTracingManager', 'instrument']
