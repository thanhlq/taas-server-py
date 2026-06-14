from .config import (
    is_elk_tracing_enabled,
    is_otel_tracing_enabled,
    is_tracing_enabled,
)



if is_otel_tracing_enabled():
    from .opentelemetry import (
        instrument,
        LogAdapter,
        TracingManager,
    )

else:
    from .defaults import noop_instrument as instrument
    from .base_logger import DefaultLogAdapter as LogAdapter
    from .noop_tracing_manager import NoopTracingManager as TracingManager


__all__ = ['instrument']
