"""
🔭 OpenTelemetry Configuration Module

For OTLP/HTTP, exporters in the SDK construct signal-specific URLs when this
environment variable is set. This means that if you’re sending traces, metrics,
and logs, the following URLs are constructed from the example above:

Traces: "http://my-api-endpoint/v1/traces"
Metrics: "http://my-api-endpoint/v1/metrics"
Logs: "http://my-api-endpoint/v1/logs"
"""

from logging import INFO
from typing import Literal, Optional

from foundation.config import Settings, get_settings
from foundation.config.log import LogSettings
from foundation.config.instrument_settings import InstrumentSettings
from foundation.observability.types import Logging, Tracing
from foundation.utils.encoding import to_base64
from foundation.utils.singleton import singleton


@singleton
class OtelConfig:
    """
    [SINGLETON] Configuration for OTEL logging adapter.
    The central configuration class for OpenTelemetry logging and tracing.
    """

    _instance: Optional['OtelConfig'] = None

    service_name: str
    host_name: Optional[str] = None
    """ Important since Grafana Cloud charges based on the host name. """

    sampling_rate: float = 1.0  # Default to 100% sampling
    auth_user: Optional[str] = None
    auth_password: Optional[str] = None
    is_development: bool = False

    log_exporter_protocol: Literal['http', 'grpc'] = 'http'
    log_exporter_endpoint: str
    log_exporter_insecured: bool

    trace_exporter_protocol: str = 'http'
    trace_exporter_endpoint: str
    trace_exporter_insecured: bool

    @property
    def log_settings(self) -> LogSettings:
        settings = get_settings()
        return settings.log

    @property
    def tracing_settings(self) -> InstrumentSettings:
        settings = get_settings()
        return settings.instrument

    @property
    def log_level(self) -> int:
        return self.log_settings.LOG_LEVEL or INFO

    def __init__(self):
        self.validate_config()

    @staticmethod
    def get_instance() -> 'OtelConfig':
        if OtelConfig._instance is None:
            OtelConfig._instance = OtelConfig()
        return OtelConfig._instance

    def is_auth_enabled(self) -> bool:
        """Check if authentication is enabled for OTEL logging exporter"""
        settings = self.tracing_settings
        return (
            settings.OTEL_AUTH_TYPE is not None
            and settings.OTEL_AUTH_TYPE.strip() != ''
        )

    def get_auth_type(self) -> Optional[str]:
        """basic, None"""
        settings = self.tracing_settings
        auth_type = settings.OTEL_AUTH_TYPE
        if auth_type is not None:
            return auth_type.strip().lower()
        return None

    def get_log_exporter_protocol(self) -> str:
        return self.log_exporter_protocol

    def get_log_exporter_endpoint(self) -> str:
        return self.log_exporter_endpoint

    def get_log_exporter_insecured(self) -> bool:
        return self.log_exporter_insecured

    def is_otel_logging_enabled(self) -> bool:
        settings = self.log_settings
        if self.log_settings.LOG_ADAPTERS:
            return (
                Logging.LOG_ADAPTER_OTLP_HTTP in settings.LOG_ADAPTERS
                or Logging.LOG_ADAPTER_OTLP_GRPC in settings.LOG_ADAPTERS
            )
        return False

    # def is_console_logging_enabled(self) -> bool:
    #     settings = get_app_settings()
    #     if (settings.LOG_ADAPTERS):
    #         return (
    #             Logging.LOG_ADAPTER_CONSOLE in settings.LOG_ADAPTERS
    #         )
    #     return False

    # def is_file_logging_enabled(self) -> bool:
    #     settings = get_app_settings()
    #     if (settings.LOG_ADAPTERS):
    #         return (
    #             Logging.LOG_ADAPTER_FILE in settings.LOG_ADAPTERS
    #         )
    #     return False

    def is_tracing_enabled(self) -> bool:
        return self.tracing_settings.is_tracing_enabled()

    def is_tracing_console_enabled(self) -> bool:
        settings = self.tracing_settings
        return bool(
            settings.TRACING_ADAPTERS
            and Tracing.TRACING_ADAPTER_CONSOLE in settings.TRACING_ADAPTERS
        )

    def build_basic_auth_headers(
        self, headers: Optional[dict] = None
    ) -> Optional[dict[str, str]]:
        headers = None
        if self.is_auth_enabled():
            headers = {} if headers is None else headers
            auth_string = f'{self.auth_user}:{self.auth_password}'
            encoded_auth = to_base64(auth_string)
            headers['Authorization'] = f'Basic {encoded_auth}'
        return headers

    def validate_config(self):
        settings: Settings = get_settings()
        self.service_name = settings.instrument.TRACING_SERVICE_NAME or settings.app.NAME
        self.host_name = settings.instrument.HOST_NAME
        self.is_development = settings.environment == 'development'
        self.auth_user = settings.instrument.OTEL_AUTH_USER
        self.auth_password = settings.instrument.OTEL_AUTH_PASSWORD
        self.sampling_rate = settings.instrument.SAMPLING_RATE

        # LOGGING

        if (
            Logging.LOG_ADAPTER_OTLP_HTTP in settings.log.LOG_ADAPTERS
            and Logging.LOG_ADAPTER_OTLP_GRPC in settings.log.LOG_ADAPTERS
        ):
            raise ValueError(
                'Cannot use both OTLP HTTP and OTLP gRPC logging adapters simultaneously.'
            )

        if self.get_auth_type() == 'basic':
            if (
                not settings.instrument.OTEL_AUTH_USER
                or not settings.instrument.OTEL_AUTH_PASSWORD
            ):
                raise ValueError(
                    'OTEL_AUTH_USER and OTEL_AUTH_PASSWORD must be set for Basic authentication'
                )

        self.log_exporter_protocol = (
            'http'
            if Logging.LOG_ADAPTER_OTLP_HTTP in settings.log.LOG_ADAPTERS
            else 'grpc'
        )

        if self.log_exporter_protocol == 'http':
            self.log_exporter_endpoint = (
                settings.otel.OTEL_LOGGING_OTLP_HTTP_ENDPOINT
                or settings.otel.OTEL_EXPORTER_OTLP_ENDPOINT
                or Logging.LOG_OTEL_HTTP_ENDPOINT_DEFAULT
            )
            if not self.log_exporter_endpoint.endswith('/v1/logs'):
                self.log_exporter_endpoint = f'{self.log_exporter_endpoint}/v1/logs'
        else:
            self.log_exporter_endpoint = (
                settings.otel.OTEL_LOGGING_OTLP_GRPC_ENDPOINT
                or settings.otel.OTEL_EXPORTER_OTLP_ENDPOINT
                or Logging.LOG_OTEL_GRPC_ENDPOINT_DEFAULT
            )

        if settings.otel.OTEL_EXPORTER_OTLP_INSECURE is not None:
            self.log_exporter_insecured = settings.otel.OTEL_EXPORTER_OTLP_INSECURE
        else:
            self.log_exporter_insecured = (
                True if self.log_exporter_endpoint.startswith('http://') else False
            )

        # TRACING
        if (
            Tracing.TRACING_ADAPTER_OTLP_HTTP in settings.instrument.TRACING_ADAPTERS
            and Tracing.TRACING_ADAPTER_OTLP_GRPC in settings.instrument.TRACING_ADAPTERS
        ):
            raise ValueError(
                'Cannot use both OTLP HTTP and OTLP gRPC logging adapters simultaneously.'
            )

        self.trace_exporter_protocol = (
            'http'
            if Tracing.TRACING_ADAPTER_OTLP_HTTP in settings.instrument.TRACING_ADAPTERS
            else 'grpc'
        )

        if self.trace_exporter_protocol == 'http':
            self.trace_exporter_endpoint = (
                settings.otel.OTEL_TRACING_OTLP_HTTP_ENDPOINT
                or settings.otel.OTEL_EXPORTER_OTLP_ENDPOINT
                or Tracing.TRACING_OTEL_HTTP_ENDPOINT_DEFAULT
            )
            if not self.trace_exporter_endpoint.endswith('/v1/traces'):
                self.trace_exporter_endpoint = (
                    f'{self.trace_exporter_endpoint}/v1/traces'
                )
        else:
            self.trace_exporter_endpoint = (
                settings.otel.OTEL_TRACING_OTLP_GRPC_ENDPOINT
                or settings.otel.OTEL_EXPORTER_OTLP_ENDPOINT
                or Tracing.TRACING_OTEL_GRPC_ENDPOINT_DEFAULT
            )

        if settings.otel.OTEL_EXPORTER_OTLP_INSECURE is not None:
            self.trace_exporter_insecured = settings.otel.OTEL_EXPORTER_OTLP_INSECURE
        else:
            self.trace_exporter_insecured = (
                True if self.trace_exporter_endpoint.startswith('http://') else False
            )

        # print(
        #     f'🔍 OTEL Logger Config, endpoint: {self.log_exporter_endpoint}, protocol: {self.log_exporter_protocol}, insecure: {self.log_exporter_insecured}'
        # )
        # print(
        #     f'🔭 OTEL Tracing Config, endpoint: {self.trace_exporter_endpoint}, protocol: {self.trace_exporter_protocol}, insecure: {self.trace_exporter_insecured}'
        # )
