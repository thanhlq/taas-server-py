"""The default implementatios when no specific observability implementation is enabled. It provides a noop instrument decorator and a default log adapter that does nothing. The noop instrument decorator simply returns the original function or class without any instrumentation, while the default log adapter can be used to log messages without any integration with OpenTelemetry or other tracing systems. This allows the application to run without any observability features when they are not needed or when the configuration is not set up for it."""
import logging
from logging import Logger
from typing import Any, Optional

from foundation.observability.types import IContextTracer, ITracingManager
from foundation.utils.decorators import empty_decorator


def noop_instrument(
    _func_or_class=None,
    *,
    span_name: str = '',
    record_exception: bool = True,
    attributes: dict[str, str] | None = None,
    existing_tracer=None,
    ignore: bool = False,
):
    """An empty instrument decorator used when no tracing implementation is enabled. It simply returns the original function or class without any"""
    if _func_or_class is None:
        return empty_decorator
    else:
        return empty_decorator(_func_or_class)


class NoopContextTracer(IContextTracer):
    """A noop context tracer that does nothing.

    It satisfies the ``IContextTracer`` contract so it can be used as a drop-in
    span/context manager when tracing is disabled. All operations are no-ops and
    chainable methods return ``self`` so calling code behaves identically whether
    or not a real tracing backend is configured.
    """

    def __init__(
        self, span_name: str, traceparent: Optional[str] = None, ctx: Any = None
    ):
        self.span_name = span_name
        self.traceparent = traceparent
        self.ctx = ctx

    def __enter__(self) -> 'NoopContextTracer':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Returning None (falsy) never suppresses exceptions.
        return None

    def set_attribute(self, key: str, value: Any):
        return None

    def record_exception(self, e: Optional[Exception]) -> 'NoopContextTracer':
        return self


class NoopTracingManager(ITracingManager):
    """A noop tracing manager used when no tracing implementation is enabled.

    Provides a safe, do-nothing implementation of the ``ITracingManager``
    interface. Every method returns an inert value (``None``, an empty
    collection, or the :class:`NoopContextTracer` class) so the rest of the
    application can use tracing APIs unconditionally without guarding for a
    missing backend.
    """
    _logger: Logger | None = None

    def __init__(self, logger: Optional[Logger] = None):
        # super().__init__()
        self._logger = logger

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = logging.getLogger('NoopTracingManager')
        return self._logger

    def get_context_tracer(self) -> type[IContextTracer]:
        return NoopContextTracer

    def get_tracer(self, name: Optional[str] = None) -> Any:
        return None

    def get_current_trace_id(self) -> Optional[str]:
        return None

    def get_current_span(self) -> Any:
        return None

    def get_current_span_id(self) -> Optional[str]:
        return None

    def capture_exception(self, e: Exception):
        self.logger.error(f'NoopTracingManager captured exception: {e}', exc_info=True)
        return None

    def get_carrier(self) -> dict[str, str]:
        return {}

    def get_propagated_aiokafka_headers(self) -> list[tuple[str, bytes]]:
        return []

    def get_faust_sensor(self) -> Any:
        return None
