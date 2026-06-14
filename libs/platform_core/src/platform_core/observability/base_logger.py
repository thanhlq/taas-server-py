import logging
from abc import ABC
from typing import Any, Optional

from platform_core.cli import cli_print_warning
from platform_core.config import get_settings
from platform_core.config.log import LogSettings
from platform_core.observability.types import Logging

type LogLevel = int

LOG_COLOR_CODES = {
    'DEBUG': '\033[34m',  # Blue
    'INFO': '\033[32m',  # Green
    'WARNING': '\033[33m',  # Yellow
    'ERROR': '\033[31m',  # Red
    'CRITICAL': '\033[91m',  # Bright Red
}
RESET_CODE = '\033[0m'

""" Including  """
LOG_FMT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
# LOG_FMT = '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s | %(message)s'
LOG_FMT_NO_NAME = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
LOG_FMT_THREAD = '%(asctime)s [%(processName)s: %(process)d] [%(threadName)s: %(thread)d] [%(levelname)s] %(name)s: %(message)s'
ROOT_LOGGER_NAME = 'TAAS'


class DetailedFormatter(logging.Formatter):
    """
    A detailed formatter that includes timestamp, level, logger name,
    function name, line number, and message with optional color coding.
    """

    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors
        super().__init__(
            # fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            fmt=LOG_FMT,
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    def format(self, record):
        if self.use_colors:
            color_code = LOG_COLOR_CODES.get(record.levelname, '')
            record.levelname = f'{color_code}{record.levelname}{RESET_CODE}'
        return super().format(record)


class BaseLogAdapter(ABC):
    """
    A base logger adapter class that will be responsible for managing logging settings and handlers.
    """

    _delegate: logging.Logger
    _level: LogLevel = logging.INFO
    _format: str
    _log_settings: LogSettings

    def __init__(self, settings: LogSettings):
        self._level = settings.LOG_LEVEL
        self._format = settings.LOG_FORMAT or Logging.LOG_FORMAT_STANDARD
        self._log_settings = settings

    def get_internal_logger(self) -> logging.Logger:
        """Get the underlying Python logger."""
        return self._delegate

    def is_console_logging_enabled(self) -> bool:
        if self._log_settings.LOG_ADAPTERS:
            return Logging.LOG_ADAPTER_CONSOLE in self._log_settings.LOG_ADAPTERS
        return False

    def is_file_logging_enabled(self) -> bool:
        if self._log_settings.LOG_ADAPTERS:
            return Logging.LOG_ADAPTER_FILE in self._log_settings.LOG_ADAPTERS
        return False

    def create_logger(self, name: str = ROOT_LOGGER_NAME) -> logging.Logger:
        """Create and configure the underlying Python logger."""
        logger = logging.Logger(name, level=self._level)
        if self.is_console_logging_enabled():
            logger.addHandler(self.get_console_log_handler())
        if self.is_file_logging_enabled():
            logger.addHandler(self.get_file_log_handler())

        handler = self.get_handler()
        if handler:
            logger.addHandler(handler)
        return logger

    def get_console_log_handler(self) -> logging.Handler:
        handler = logging.StreamHandler()
        settings = self._log_settings

        if Logging.LOG_FORMAT_DETAILED == self._format:
            handler.setFormatter(DetailedFormatter(settings.LOG_WITH_COLOR))
        elif Logging.LOG_FORMAT_JSON == self._format:
            raise NotImplementedError('JSON log format is not implemented yet.')
        else:
            handler.setFormatter(logging.Formatter(LOG_FMT))
        return handler

    def get_file_log_handler(self) -> logging.Handler:
        settings = self._log_settings
        file_handler = logging.FileHandler(settings.get_log_file_path(), mode='a')
        if Logging.LOG_FORMAT_DETAILED == self._format:
            file_handler.setFormatter(DetailedFormatter(use_colors=False))
        elif Logging.LOG_FORMAT_JSON == self._format:
            raise NotImplementedError('JSON log format is not implemented yet.')
        else:
            file_handler.setFormatter(logging.Formatter(LOG_FMT))
        return file_handler

    def get_handler(self) -> Optional[logging.Handler]:
        cli_print_warning(
            'BaseLogAdapter.get_handler called - should be overridden by subclasses if needed'
        )
        return None

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log debug message with structured context."""
        self._log_with_context(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log info message with structured context."""
        self._log_with_context(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log warning message with structured context."""
        self._log_with_context(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log error message with structured context."""
        self._log_with_context(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log critical message with structured context."""
        self._log_with_context(logging.CRITICAL, msg, *args, **kwargs)

    def log(self, level: LogLevel, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log message at specified level with structured context."""
        self._log_with_context(level, msg, *args, **kwargs)

    def log_with_context(
        self, level: LogLevel, msg: Any, *args: Any, **kwargs: Any
    ) -> None:
        """This method should be implemented by subclasses to add context"""
        # Separate standard logging kwargs from custom context
        exc_info = kwargs.pop('exc_info', None)
        stack_info = kwargs.pop('stack_info', None)
        stacklevel = kwargs.pop('stacklevel', 1)
        extra = kwargs.pop('extra', {})

        # Format message with args if provided (standard logging behavior)
        if args:
            message = str(msg) % args
        else:
            message = str(msg)

        # Create structured log record
        if kwargs:
            # For ECS logging, add context as extra fields directly
            # ECS formatter handles proper structuring and timestamps
            for key, value in kwargs.items():
                extra[key] = value

        self._delegate._log(
            level,
            message,
            (),
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
        )

    def _log_with_context(
        self, level: LogLevel, msg: Any, *args: Any, **kwargs: Any
    ) -> None:
        """This should be implemented by subclasses to add context"""
        if not self._delegate.isEnabledFor(level):
            return
        self.log_with_context(level, msg, *args, **kwargs)


class DefaultLogAdapter(BaseLogAdapter):
    """
    A simple default logger implementation of ILogAdapter interface.
    Only console or file logging is supported.
    """

    def __init__(self):
        super().__init__(get_settings().log)

    def get_handler(self):
        return None

    def create_logger(self, name: str = ROOT_LOGGER_NAME) -> logging.Logger:
        return super().create_logger(name)
