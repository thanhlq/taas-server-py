from __future__ import annotations

from dataclasses import dataclass, field

from foundation.observability.types import Tracing
from foundation.utils.env_utils import get_env

# Defined locally (like the other config modules, e.g. log.py / cache.py) to
# avoid a circular import: ``foundation.config.__init__`` imports ``settings``,
# which imports this module, so importing CONFIG_PREFIX from the package here
# would run before the package namespace is populated.
CONFIG_PREFIX = 'TAAS'


@dataclass
class InstrumentSettings:
    """Monitoring, APM and OpenTelemetry observability configuration.

    Ported from the legacy pydantic ``AppSetting`` (MONITORING & OBSERVABILITY
    section). Env-var names are kept identical so existing deployment
    configuration keeps working.
    """

    TRACING_ADAPTERS: str = field(default_factory=get_env('TRACING_ADAPTERS', ''))
    """📡 Values: otlp-http, otlp-grpc, console, elk"""

    OTEL_AUTH_TYPE: str | None = field(
        default_factory=get_env('OTEL_AUTH_TYPE', None, str)
    )
    """🔐 OpenTelemetry authentication type (basic, token, oidc).

    Only defined when you want to export traces/logs to a secured OTEL
    collector or directly to a SaaS monitoring service like Grafana Cloud.
    """

    OTEL_AUTH_USER: str | None = field(
        default_factory=get_env('OTEL_AUTH_USER', None, str)
    )
    OTEL_AUTH_PASSWORD: str | None = field(
        default_factory=get_env('OTEL_AUTH_PASSWORD', None, str)
    )
    """🔗 OpenTelemetry collector endpoint (gRPC)"""

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = field(
        default_factory=get_env('OTEL_EXPORTER_OTLP_ENDPOINT', None, str)
    )
    """🔗 OpenTelemetry collector general endpoint; if defined you can skip all
    endpoints below."""

    OTEL_LOGGING_OTLP_HTTP_ENDPOINT: str | None = field(
        default_factory=get_env(
            'OTEL_LOGGING_OTLP_HTTP_ENDPOINT', 'http://localhost:4318/v1/logs'
        )
    )
    OTEL_LOGGING_OTLP_GRPC_ENDPOINT: str | None = field(
        default_factory=get_env(
            'OTEL_LOGGING_OTLP_GRPC_ENDPOINT', 'http://localhost:4317'
        )
    )
    # See https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/#otel_exporter_otlp_traces_endpoint
    OTEL_TRACING_OTLP_HTTP_ENDPOINT: str | None = field(
        default_factory=get_env(
            'OTEL_TRACING_OTLP_HTTP_ENDPOINT', 'http://localhost:4318/v1/traces'
        )
    )
    OTEL_TRACING_OTLP_GRPC_ENDPOINT: str | None = field(
        default_factory=get_env(
            'OTEL_TRACING_OTLP_GRPC_ENDPOINT', 'http://localhost:4317'
        )
    )

    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED: bool = field(
        default_factory=get_env('OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED', True)
    )
    """🤖 Enable automatic Python logging instrumentation"""

    OTEL_EXPORTER_OTLP_INSECURE: bool | None = field(
        default_factory=get_env('OTEL_EXPORTER_OTLP_INSECURE', None, bool)
    )
    """🔓 Use insecure connection to OTLP collector (no TLS); None for
    auto-detection."""

    OTEL_SERVICE_NAME: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_SERVICE_NAME', 'ews')
    )
    """🏷️ Service name for tracing identification"""

    # 🦌 ELK Stack / Elastic APM Configuration
    ELK_APM_ENABLED: bool = field(
        default_factory=get_env('ELK_APM_ENABLED', False, bool)
    )
    """📊 Enable Elastic APM monitoring (disabled by default to avoid connection
    issues)."""

    ELK_APM_HOST: str = field(
        default_factory=get_env('ELK_APM_HOST', 'http://localhost:8200')
    )
    """🔗 Elastic APM server URL (Docker: http://elasticapm:8200)"""

    TRACING_SERVICE_NAME: str | None = field(
        default_factory=get_env('TRACING_SERVICE_NAME', 'taas', str)
    )
    """🏷️ Service name for APM identification"""

    ELK_APM_SECRET: str | None = field(
        default_factory=get_env('ELK_APM_SECRET', None, str)
    )
    """🔑 Elastic APM secret token"""

    SAMPLING_RATE: float = field(default_factory=get_env('SAMPLING_RATE', 0.1, float))
    HOST_NAME: str | None = field(default_factory=get_env('HOST_NAME', None, str))
    """🏷️ Host name for APM identification"""

    def is_tracing_enabled(self) -> bool:
        if self.TRACING_ADAPTERS:
            return (
                Tracing.TRACING_ADAPTER_OTLP_HTTP in self.TRACING_ADAPTERS
                or Tracing.TRACING_ADAPTER_OTLP_GRPC in self.TRACING_ADAPTERS
                or Tracing.TRACING_ADAPTER_CONSOLE in self.TRACING_ADAPTERS
            )
        return False
