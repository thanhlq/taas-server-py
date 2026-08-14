from foundation.config import Settings, get_settings
from foundation.observability.types import Tracing


def is_tracing_enabled() -> bool:
    return is_elk_tracing_enabled() or is_otel_tracing_enabled()


def is_elk_tracing_enabled() -> bool:
    settings: Settings = get_settings()
    return Tracing.TRACING_ADAPTER_ELK in settings.instrument.TRACING_ADAPTERS


def is_otel_tracing_enabled() -> bool:
    settings: Settings = get_settings()
    return (
        Tracing.TRACING_ADAPTER_OTLP_HTTP in settings.instrument.TRACING_ADAPTERS
        or Tracing.TRACING_ADAPTER_OTLP_GRPC in settings.instrument.TRACING_ADAPTERS
    )
