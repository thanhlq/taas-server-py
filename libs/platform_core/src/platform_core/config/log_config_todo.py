from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from importlib.util import find_spec
from logging import Logger
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeAlias, Union, cast

from platform_core.exceptions import (
    ImproperlyConfiguredException,
)
from platform_core.types.callable_types import ExceptionLoggingHandler, GetLogger

__all__ = ('BaseLoggingConfig', 'LoggingConfig')


if TYPE_CHECKING:
    from typing import NoReturn

    from platform_core.types import Scope


default_handlers: dict[str, dict[str, Any]] = {
    'console': {
        'class': 'logging.StreamHandler',
        'level': 'DEBUG',
        'formatter': 'standard',
    },
    'queue_listener': {
        'class': 'litestar.logging.standard.QueueListenerHandler',
        'level': 'DEBUG',
        'formatter': 'standard',
    },
}

if sys.version_info >= (3, 12, 0):
    default_handlers['queue_listener'].update(
        {
            'class': 'logging.handlers.QueueHandler',
            'queue': {
                '()': 'queue.Queue',
                'maxsize': -1,
            },
            'listener': 'litestar.logging.standard.LoggingQueueListener',
            'handlers': ['console'],
        }
    )

    # do not format twice, the console handler will do the job
    del default_handlers['queue_listener']['formatter']


default_picologging_handlers: dict[str, dict[str, Any]] = {
    'console': {
        'class': 'picologging.StreamHandler',
        'level': 'DEBUG',
        'formatter': 'standard',
    },
    'queue_listener': {
        'class': 'litestar.logging.picologging.QueueListenerHandler',
        'level': 'DEBUG',
        'formatter': 'standard',
    },
}


def _get_default_formatters() -> dict[str, dict[str, Any]]:
    return {
        'standard': {
            'format': '%(levelname)s - %(asctime)s - %(name)s - %(module)s - %(message)s'
        },
    }


def _get_default_loggers() -> dict[str, dict[str, Any]]:
    return {
        'taas': {
            'level': 'INFO',
            'handlers': ['queue_listener'],
            'propagate': False,
        },
    }


def get_logger_placeholder(_: str | None = None) -> NoReturn:
    """Raise: An :class:`ImproperlyConfiguredException <.exceptions.ImproperlyConfiguredException>`"""
    raise ImproperlyConfiguredException(
        "cannot call '.get_logger' without passing 'logging_config' to the Litestar constructor first"
    )


def _get_default_logging_module() -> str:
    if find_spec('picologging'):
        return 'picologging'
    return 'logging'


def _get_default_handlers(logging_module: str) -> dict[str, dict[str, Any]]:
    """Return the default logging handlers for the config.

    Returns:
        A dictionary of logging handlers
    """
    if logging_module == 'picologging':
        return default_picologging_handlers
    return default_handlers


class BaseLoggingConfig(ABC):
    """Abstract class that should be extended by logging configs."""

    __slots__ = ('exception_logging_handler', 'log_exceptions')

    log_exceptions: Literal['always', 'debug', 'never']
    """Should exceptions be logged, defaults to log exceptions when ``app.debug == True``'"""
    exception_logging_handler: ExceptionLoggingHandler | None
    """Handler function for logging exceptions."""
    disable_stack_trace: set[Union[int, type[Exception]]]  # noqa: UP007
    """Set of http status codes and exceptions to disable stack trace logging for."""

    @abstractmethod
    def configure(self) -> GetLogger:
        """Return logger with the given configuration.

        Returns:
            A 'logging.getLogger' like function.
        """
        raise NotImplementedError('abstract method')

    @staticmethod
    def set_level(logger: Any, level: int) -> None:
        """Provides a consistent interface to call `setLevel` for all loggers."""
        raise NotImplementedError('abstract method')


def _default_exception_logging_handler(
    logger: Logger, scope: Scope, tb: list[str]
) -> None:
    logger.error(
        'Uncaught exception (connection_type=%s, path=%r):',
        scope['type'],
        scope['path'],
    )


@dataclass
class LoggingConfig(BaseLoggingConfig):
    """Configuration class for standard logging."""

    logging_module: str = field(default_factory=_get_default_logging_module)
    """Logging module. ``logging`` and ``picologging`` are supported. ``picologging`` will be used by default if
    installed."""
    version: Literal[1] = field(default=1)
    """The only valid value at present is 1."""
    incremental: bool = field(default=False)
    """Whether the configuration is to be interpreted as incremental to the existing configuration.

    Notes:
        - This option is ignored for 'picologging'
    """
    disable_existing_loggers: bool = field(default=False)
    """Whether any existing non-root loggers are to be disabled."""
    filters: dict[str, dict[str, Any]] | None = field(default=None)
    """A dict in which each key is a filter id and each value is a dict describing how to configure the
    corresponding Filter_ instance.

    .. _Filter: https://docs.python.org/3/library/logging.html#filter-objects
    """
    propagate: bool = field(default=True)
    """If messages must propagate to handlers higher up the logger hierarchy from this logger.

    .. deprecated:: 2.10.0
        This parameter is deprecated. It will be removed in a future release. Use ``propagate`` at the logger level.
    """
    formatters: dict[str, dict[str, Any]] = field(
        default_factory=_get_default_formatters
    )
    """A dict in which each key is a formatter and each value is a dict describing how to configure the
    corresponding Formatter_ instance. A ``standard`` formatter is provided.

    .. _Formatter: https://docs.python.org/3/library/logging.html#formatter-objects
    """
    handlers: dict[str, dict[str, Any]] = field(default_factory=dict)
    """A dict in which each key is a handler id and each value is a dict describing how to configure the
    corresponding Handler_ instance. Two handlers are provided, ``console`` and ``queue_listener``.

    .. _Handler: https://docs.python.org/3/library/logging.html#handler-objects
    """
    loggers: dict[str, dict[str, Any]] = field(default_factory=_get_default_loggers)
    """A dict in which each key is a logger name and each value is a dict describing how to configure the
    corresponding Logger_ instance. A ``litestar`` logger is mandatory and will be configured as required.

    .. _Logger: https://docs.python.org/3/library/logging.html#logger-objects
    """
    root: dict[str, dict[str, Any] | list[Any] | str] = field(
        default_factory=lambda: {
            'handlers': ['queue_listener'],
            'level': 'INFO',
        }
    )
    """This will be the configuration for the root logger.

    Processing of the configuration will be as for any logger, except that the propagate setting will not be applicable.
    """
    configure_root_logger: bool = field(default=True)
    """Should the root logger be configured, defaults to True for ease of configuration."""
    log_exceptions: Literal['always', 'debug', 'never'] = field(default='debug')
    """Should exceptions be logged, defaults to log exceptions when 'app.debug == True'"""
    disable_stack_trace: set[Union[int, type[Exception]]] = field(default_factory=set)  # noqa: UP007
    """Set of http status codes and exceptions to disable stack trace logging for."""
    traceback_line_limit: int = field(default=-1)
    """Max number of lines to print for exception traceback.

    .. deprecated:: 2.9.0
        This parameter is deprecated and ignored. It will be removed in a future release.
    """
    exception_logging_handler: ExceptionLoggingHandler | None = field(default=None)
    """Handler function for logging exceptions."""

    def __post_init__(self) -> None:
        if 'standard' not in self.formatters:
            self.formatters['standard'] = _get_default_formatters()['standard']

        if 'console' not in self.handlers:
            self.handlers['console'] = _get_default_handlers(self.logging_module)[
                'console'
            ]

        if 'queue_listener' not in self.handlers:
            self.handlers['queue_listener'] = _get_default_handlers(
                self.logging_module
            )['queue_listener']

        if 'litestar' not in self.loggers:
            self.loggers['litestar'] = _get_default_loggers()['litestar']

        if self.log_exceptions != 'never' and self.exception_logging_handler is None:
            # FIXME:
            self.exception_logging_handler = _default_exception_logging_handler

    def configure(self) -> GetLogger:
        """Return logger with the given configuration.

        Returns:
            A 'logging.getLogger' like function.
        """

        excluded_fields: set[str] = {
            'logging_module',
            'configure_root_logger',
            'exception_logging_handler',
            'log_exceptions',
            'propagate',
            'traceback_line_limit',
            'disable_stack_trace',
        }

        if not self.configure_root_logger:
            excluded_fields.add('root')

        # if self.logging_module == 'picologging':
        #     try:
        #         from picologging import (  # pyright: ignore[reportMissingImports,reportGeneralTypeIssues]
        #             config,  # pyright: ignore[reportMissingImports,reportGeneralTypeIssues]
        #             getLogger,  # pyright: ignore[reportMissingImports,reportGeneralTypeIssues]
        #         )
        #     except ImportError as e:
        #         raise MissingDependencyException('picologging') from e

        #     excluded_fields.add('incremental')
        # else:
        #     from logging import (  # type: ignore[no-redef,assignment,unused-ignore]
        #         config,
        #         getLogger,
        #     )

        from logging import (  # type: ignore[no-redef,assignment,unused-ignore]
            config,
            getLogger,
        )

        values = {
            _field.name: getattr(self, _field.name)
            for _field in fields(self)
            if getattr(self, _field.name) is not None
            and _field.name not in excluded_fields
        }

        config.dictConfig(values)
        return cast('Callable[[str], Logger]', getLogger)

    @staticmethod
    def set_level(logger: Logger, level: int) -> None:
        """Provides a consistent interface to call `setLevel` for all loggers."""
        logger.setLevel(level)
