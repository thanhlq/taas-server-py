"""
OpenTelemetry-compatible logging implementation.
Examples: https://github.com/open-telemetry/opentelemetry-python/blob/main/docs/examples/logs/example.py
"""

from logging import INFO, Filter
from typing import Any, Optional

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter as OTLPLogExporterGRPC,
)
from opentelemetry.exporter.otlp.proto.http._log_exporter import (
    OTLPLogExporter as OTLPLogExporterHTTP,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from platform_core.config import get_settings
from platform_core.observability.base_logger import LOG_FMT, BaseLogAdapter

from .otel_config import OtelConfig


class RemoveExtra(Filter):
    def filter(self, record):
        # print(f'record message: {record.msg}')
        # del record.extra
        return True


class OtelLogProvider:
    _instance: Optional['OtelLogProvider'] = None
    logger_provider: LoggerProvider

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__()
            self.logger_provider = self.init_otel_log_provider()
            self._initialized = True

    def init_otel_log_provider(self) -> LoggerProvider:
        config: OtelConfig = OtelConfig.get_instance()
        resource = Resource({SERVICE_NAME: config.service_name})
        provider = LoggerProvider(resource=resource)
        exporter = None

        if config.is_auth_enabled() and config.log_exporter_protocol == 'grpc':
            raise ValueError(
                '[logs] gRPC protocol does not support authentication headers. Use [otlp-http] protocol for LOG_ADAPTERS.'
            )

        if config.log_exporter_protocol == 'grpc':
            exporter = OTLPLogExporterGRPC(
                endpoint=config.log_exporter_endpoint,
                insecure=config.log_exporter_insecured,
            )
        else:
            exporter = OTLPLogExporterHTTP(
                endpoint=config.log_exporter_endpoint,
                headers=config.build_basic_auth_headers(),
            )

        processor = BatchLogRecordProcessor(exporter)
        provider.add_log_record_processor(processor)

        set_logger_provider(provider)
        return provider


class OtelLogAdapter(BaseLogAdapter):
    """OpenTelemetry-compatible logger adapter that ."""

    _insecured: bool = False
    _endpoint: bool = False

    def __init__(self):
        super().__init__(get_settings().log)

    def get_handler(self):
        handler = LoggingHandler(
            level=INFO, logger_provider=OtelLogProvider().logger_provider
        )
        # Example of adding a filter to remove extra fields if needed
        # handler.addFilter(RemoveExtra())
        return handler

    # def create_logger(self, name: str | None = None) -> logging.Logger:
    #     logger = super().create_logger(name)
    #     logger.addHandler(self.get_handler())
    #     return logger


UVICORN_LOGGING_CONFIG: dict[str, Any] = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            '()': 'uvicorn.logging.DefaultFormatter',
            # 'fmt': '%(levelprefix)s %(message)s',
            'fmt': LOG_FMT,
            'use_colors': None,
        },
        'access': {
            '()': 'uvicorn.logging.AccessFormatter',
            'fmt': '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',  # noqa: E501
        },
    },
    'handlers': {
        'default': {
            'formatter': 'default',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stderr',
        },
        'access': {
            'formatter': 'access',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
    },
    'loggers': {
        'uvicorn': {'handlers': ['default'], 'level': 'INFO', 'propagate': False},
        'uvicorn.error': {'level': 'INFO'},
        'uvicorn.access': {'handlers': ['access'], 'level': 'INFO', 'propagate': False},
    },
}

def build_uvicorn_otel_log_config() -> dict:
    return UVICORN_LOGGING_CONFIG
