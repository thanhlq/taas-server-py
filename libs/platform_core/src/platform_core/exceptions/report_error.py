import logging
from logging import Logger
from typing import Any, Optional


def _extract_exception_chain(exception: Exception) -> list[dict[str, str]]:
    """
    Extract the chain of exceptions from an exception.

    Python exceptions can have chained exceptions through:
    - __cause__: Explicitly chained with 'raise ... from ...'
    - __context__: Implicitly chained when exception occurs during handling

    Args:
        exception: The exception to extract chain from

    Returns:
        List of exception info dicts in order [immediate cause, root cause]

    Examples:
        >>> try:
        ...     try:
        ...         int('invalid')
        ...     except ValueError as e:
        ...         raise RuntimeError("Processing failed") from e
        ... except RuntimeError as e:
        ...     chain = _extract_exception_chain(e)
        >>> # chain = [
        >>> #   {"type": "ValueError", "message": "invalid literal..."},
        >>> #   {"type": "RuntimeError", "message": "Processing failed"}
        >>> # ]
    """
    chain: list[dict[str, str]] = []
    seen: set[int] = set()  # Prevent infinite loops
    current: BaseException | None = exception

    # Walk the exception chain
    while current:
        # Prevent infinite loops
        exc_id = id(current)
        if exc_id in seen:
            break
        seen.add(exc_id)

        # Get the cause (explicit or implicit)
        # __cause__ takes precedence over __context__
        next_exc: BaseException | None = None
        chain_type = ''

        if hasattr(current, '__cause__') and current.__cause__ is not None:
            next_exc = current.__cause__
            chain_type = 'explicit'
        elif hasattr(current, '__context__') and current.__context__ is not None:
            # Only include context if not suppressed
            if not getattr(current, '__suppress_context__', False):
                next_exc = current.__context__
                chain_type = 'implicit'

        # Add to chain if we found a next exception
        if next_exc:
            chain.append(
                {
                    'type': next_exc.__class__.__name__,
                    'message': str(next_exc) or next_exc.__class__.__name__,
                    'chain_type': chain_type,
                }
            )
            current = next_exc
        else:
            break

    return chain


def report_error(
    error_message: str | Exception,
    *,
    title: Optional[str] = None,
    extra_context: Optional[dict[str, Any]] = None,
    log_traceback: bool = True,
    capture_in_span: bool = True,
    logger: Optional[Logger] = None,
) -> None:
    """
    Reports an error message to the observability system.

    This function integrates with both logging and tracing systems to ensure
    errors are properly recorded and can be tracked across distributed systems.

    Features:
    - Logs error with structured context
    - Captures exception in active tracing span (if tracing is enabled)
    - Supports both string messages and Exception objects
    - Handles exception chaining (raise ... from ...) automatically
    - Can include additional context for debugging
    - Optional error title for better categorization
    - Thread-safe and can be called from anywhere in the codebase

    Args:
        error_message: Either a string error message or an Exception instance.
        title: Optional title/category for the error (e.g., "Payment Error", "Database Error").
            If provided, logs as "{title}, error: {error_message}".
        extra_context: Optional dictionary of additional context to log with the error.
            Useful for adding request IDs, user IDs, or other relevant metadata.
        log_traceback: Whether to include the full traceback in logs (default: True).
            Only applies when error_message is an Exception.
        capture_in_span: Whether to capture the error in the current tracing span
            (default: True). Only applies when tracing is enabled.

    Examples:
        >>> # Simple string error
        >>> report_error("Database connection failed")

        >>> # Error with title
        >>> report_error("Connection timeout", title="Database Error")
        >>> # Logs as: "Database Error, error: Connection timeout"

        >>> # Exception with title and context
        >>> try:
        ...     result = process_payment(order_id)
        ... except ValueError as e:
        ...     report_error(e, title="Payment Processing",
        ...                  extra_context={"order_id": order_id, "user_id": user_id})

        >>> # Error without traceback logging
        >>> report_error(exception, log_traceback=False)

        >>> # Chained exceptions are automatically captured
        >>> try:
        ...     try:
        ...         int('invalid')
        ...     except ValueError as e:
        ...         raise RuntimeError("Processing failed") from e
        ... except RuntimeError as e:
        ...     report_error(e)  # Logs both RuntimeError and ValueError

    Note:
        - This function never raises exceptions itself, ensuring safe error reporting
        - If tracing is not enabled, it gracefully falls back to logging only
        - Exception chains (__cause__ and __context__) are automatically extracted and logged
        - The function returns None and is meant for side effects only
    """

    _logger = logger or logging.getLogger()
    _tracing_manager = None

    # if is_tracing_enabled() and capture_in_span:
    #     _tracing_manager = TracingFactory().get_tracing_manager()

    # Determine if we're dealing with an exception or a message
    is_exception = isinstance(error_message, Exception)
    exception_obj: Optional[Exception] = None
    error_str: str = ''

    if is_exception:
        exception_obj = error_message
        error_str = str(error_message)
        # If exception message is empty, use exception type name
        if not error_str:
            error_str = exception_obj.__class__.__name__
    else:
        error_str = str(error_message)

    # Build structured log context
    log_context = {
        'error_message': error_str,
        'error_type': exception_obj.__class__.__name__
        if is_exception
        else 'ErrorMessage',
    }

    # Add title if provided
    if title:
        log_context['error_title'] = title

    # Handle exception chaining - extract chain information
    if is_exception and exception_obj:
        exception_chain = _extract_exception_chain(exception_obj)
        if exception_chain:
            log_context['exception_chain'] = exception_chain

    # Add extra context if provided
    if extra_context:
        log_context['extra_context'] = extra_context

    # Add trace context if available
    if _tracing_manager:
        try:
            trace_id = _tracing_manager.get_current_trace_id()
            span_id = _tracing_manager.get_current_span_id()
            if trace_id:
                log_context['trace_id'] = trace_id
            if span_id:
                log_context['span_id'] = span_id
        except Exception:
            # Silently ignore if getting trace context fails
            pass

    # Build log message
    if title:
        log_message = f'❌ {title}, error: {error_str}'
    else:
        log_message = f'❌ Error reported: {error_str}'

    # Log the error
    try:
        if _logger:
            if is_exception and log_traceback:
                # Log with full exception info including traceback
                _logger.error(
                    log_message,
                    exc_info=exception_obj,
                    extra=log_context,
                )
            else:
                # Log without traceback
                _logger.error(
                    log_message,
                    extra=log_context,
                )
        else:
            # Fallback to print if logger not available
            print(log_message)
            if extra_context:
                print(f'📍 Context: {extra_context}')
    except Exception as log_error:
        # Fallback if logging fails
        print(f'⚠️  Logging failed: {log_error}')
        print(f'📍 Original error: {error_str}')

    # Capture exception in tracing span if applicable
    if _tracing_manager and is_exception and exception_obj and capture_in_span:
        try:
            _tracing_manager.capture_exception(exception_obj)
        except Exception as trace_error:
            # Silently handle tracing errors to avoid cascading failures
            if _logger:
                try:
                    _logger.warning(
                        f'Failed to capture exception in tracing span: {trace_error}'
                    )
                except Exception:
                    # Even warning failed, use print as last resort
                    print(
                        f'⚠️  Failed to capture exception in tracing span: {trace_error}'
                    )


def report_error_with_traceback(
    error_message: str | Exception,
    title: Optional[str] = None,
    extra_context: Optional[dict[str, Any]] = None,
    logger: Optional[Logger] = None,
) -> None:
    """
    Convenience function that always includes the full traceback.

    Equivalent to: report_error(error_message, title=title, extra_context=extra_context, log_traceback=True)

    Args:
        error_message: Either a string error message or an Exception instance.
        title: Optional title/category for the error.
        extra_context: Optional dictionary of additional context.
    """
    report_error(
        error_message,
        title=title,
        extra_context=extra_context,
        log_traceback=True,
        capture_in_span=True,
        logger=logger,
    )


def report_error_simple(
    error_message: str | Exception,
    title: Optional[str] = None,
    logger: Optional[Logger] = None,
) -> None:
    """
    Convenience function for simple error reporting without extra context or traceback.

    Equivalent to: report_error(error_message, title=title, log_traceback=False)

    Args:
        error_message: Either a string error message or an Exception instance.
        title: Optional title/category for the error.
    """
    report_error(
        error_message,
        title=title,
        extra_context=None,
        log_traceback=False,
        capture_in_span=True,
        logger=logger,
    )
