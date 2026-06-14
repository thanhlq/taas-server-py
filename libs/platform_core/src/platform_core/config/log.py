from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platform_core.utils.env_utils import get_env
from platform_core.utils.io import get_runtime_directory, is_relative_path, join_paths

CONFIG_PREFIX = 'TAAS'
LOG_ADATPTER_CONSOLE = 'console'
LOG_ADAPTER_FILE = 'file'
LOG_ADAPTER_OTLP_HTTP = 'otlp-http'
LOG_ADAPTER_OTLP_GRPC = 'otlp-grpc'
LOG_ADAPTER_ELK = 'elk'


@dataclass
class LogSettings:
    """Logger configuration"""

    LOG_ADAPTERS: str = 'console,file,otlp-http'
    """ Values can be comma-separated list of:
        - console: terminal console
        - file: best for debug or tracing issue in local/dev environment
        - otlp-http: OpenTelemetry OTLP over HTTP
        - otlp-grpc: OpenTelemetry OTLP over gRPC
        - elk: Elastic APM logging
        - '': (empty) disable logging
    """

    # https://stackoverflow.com/a/1845097/6560549
    EXCLUDE_PATHS: str = r'\A(?!x)x'
    """Regex to exclude paths from logging."""
    INCLUDE_COMPRESSED_BODY: bool = False
    """Include 'body' of compressed responses in log output."""
    LOG_LEVEL: int = field(default_factory=get_env('LOG_LEVEL', 30))
    LOG_FORMAT: str = 'standard'
    LOG_WITH_COLOR: bool = True
    LOG_FILE_DIR: str = 'logs'
    LOG_FILE_NAME: str = 'taas.log'
    OBFUSCATE_COOKIES: set[str] = field(
        default_factory=lambda: {'session', 'XSRF-TOKEN'}
    )
    """Request cookie keys to obfuscate."""
    OBFUSCATE_HEADERS: set[str] = field(
        default_factory=lambda: {'Authorization', 'X-API-KEY', 'X-XSRF-TOKEN'}
    )
    """Attributes of the [Response][litestar.response.Response] to be
    logged."""
    SAQ_LEVEL: int = field(default_factory=get_env('SAQ_LOG_LEVEL', 50))
    """Level to log SAQ logs."""
    SQLALCHEMY_LEVEL: int = field(default_factory=get_env('SQLALCHEMY_LOG_LEVEL', 30))
    """Level to log SQLAlchemy logs."""
    ASGI_ACCESS_LEVEL: int = field(default_factory=get_env('ASGI_ACCESS_LOG_LEVEL', 30))
    """Level to log uvicorn access logs."""
    ASGI_ERROR_LEVEL: int = field(default_factory=get_env('ASGI_ERROR_LOG_LEVEL', 30))
    """Level to log uvicorn error logs."""

    def get_log_file_path(self) -> str:
        _runtime_dir = (
            os.environ.get(f'{CONFIG_PREFIX}_HOME_PATH', None)
            or get_runtime_directory()
        )
        if not self.LOG_FILE_DIR:
            log_dir = os.path.join(_runtime_dir, 'logs')
        elif is_relative_path(self.LOG_FILE_DIR):
            log_dir = join_paths(_runtime_dir, self.LOG_FILE_DIR)
        else:
            log_dir = self.LOG_FILE_DIR

        file_name = self.LOG_FILE_NAME
        log_dir_path = Path(log_dir)
        log_dir = log_dir_path.resolve()

        # Ensure the log directory exists
        os.makedirs(log_dir, exist_ok=True)

        log_filepath = os.path.join(log_dir, file_name)

        return log_filepath
