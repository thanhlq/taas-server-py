"""The default implementatios when no specific observability implementation is enabled. It provides a noop instrument decorator and a default log adapter that does nothing. The noop instrument decorator simply returns the original function or class without any instrumentation, while the default log adapter can be used to log messages without any integration with OpenTelemetry or other tracing systems. This allows the application to run without any observability features when they are not needed or when the configuration is not set up for it."""
from typing import Any, Optional

from platform_core.observability.types import IContextTracer, ITracingManager

from platform_core.utils.decorators import empty_decorator


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


class NoopTracingManager(ITracingManager):
    """A noop tracing manager used when no tracing implementation is enabled. It provides a default implementation of the ITracingManager interface that does nothing."""
    return None