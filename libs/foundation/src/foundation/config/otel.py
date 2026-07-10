
from __future__ import annotations

from dataclasses import dataclass, field

from foundation.utils.env_utils import get_env


@dataclass
class OtelSettings:
    """OpenTelemetry configuration"""

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_EXPORTER_OTLP_ENDPOINT', None, str)
    )

    OTEL_LOGGING_OTLP_HTTP_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_LOGGING_OTLP_HTTP_ENDPOINT', None, str)
    )

    OTEL_LOGGING_OTLP_GRPC_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_LOGGING_OTLP_GRPC_ENDPOINT', None, str)
    )

    OTEL_TRACING_OTLP_HTTP_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_TRACING_OTLP_HTTP_ENDPOINT', None, str)
    )

    OTEL_TRACING_OTLP_GRPC_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_TRACING_OTLP_GRPC_ENDPOINT', None, str)
    )

    OTEL_EXPORTER_OTLP_INSECURE: bool | None = field(
        default_factory=get_env('OTEL_EXPORTER_OTLP_INSECURE', None, bool)
    )
