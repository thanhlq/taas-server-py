import asyncio
import random
import signal as _signal
import threading
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.retry.types import IRetryPolicy

T = TypeVar('T')


class ExponentialBackoffRetry(IRetryPolicy):
    """
    Retry policy with exponential backoff and optional jitter.

    Implements exponential backoff: delay = min(initial_delay * (base ^ attempt), max_delay)
    With jitter: adds randomness to prevent thundering herd when multiple clients retry

    Thread-safe: Uses no shared mutable state across execute() calls.

    Use cases:
        - Transient network errors
        - Temporary service unavailability
        - Rate limiting scenarios
        - Database connection failures

    Example:
        retry_policy = ExponentialBackoffRetry(
            max_attempts=5,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0,
            jitter=True
        )

        # Synchronous function
        result = retry_policy.execute(
            func=call_external_api,
            url="https://api.example.com",
            should_retry=lambda ex: isinstance(ex, (NetworkError, TimeoutError))
        )

        # Async function
        result = await retry_policy.execute_async(
            func=async_call_api,
            url="https://api.example.com"
        )

        # As decorator
        @retry_policy.decorator()
        def risky_operation():
            # May fail and be retried
            return call_external_service()
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        name: str = 'retry_policy',
        # Additional parameters for TenacityRetry compatibility (ignored)
        wait_strategy: str = 'exponential',
        exponential_multiplier: float = 1.0,
        retry_on_exceptions: Optional[tuple] = None,
    ):
        """
        Initialize retry policy with exponential backoff.

        Args:
            max_attempts: Maximum number of attempts (including initial attempt).
                         Must be >= 1. Default: 3
            initial_delay: Initial delay in seconds before first retry.
                          Must be > 0. Default: 1.0
            max_delay: Maximum delay in seconds between retries.
                      Must be >= initial_delay. Default: 60.0
            exponential_base: Base for exponential backoff calculation.
                             Common values: 2.0 (double each time), 1.5, 3.0.
                             Must be >= 1.0. Default: 2.0
            jitter: If True, adds random jitter (0-50% of delay) to prevent
                   thundering herd. Recommended for distributed systems.
                   Default: True
            name: Name for logging purposes. Default: "retry_policy"
            wait_strategy: Strategy type (for TenacityRetry compatibility).
                          Ignored by ExponentialBackoffRetry. Default: 'exponential'
            exponential_multiplier: Multiplier (for TenacityRetry compatibility).
                                   Ignored by ExponentialBackoffRetry. Default: 1.0
            retry_on_exceptions: Exception types (for TenacityRetry compatibility).
                                Ignored by ExponentialBackoffRetry. Default: None

        Raises:
            ValueError: If parameters are invalid.

        Note:
            Parameters wait_strategy, exponential_multiplier, and retry_on_exceptions
            are accepted for API compatibility with TenacityRetry but are not used
            by this implementation. Use should_retry parameter in execute() methods
            to filter retryable exceptions.
        """
        if max_attempts < 1:
            raise ValueError(f'max_attempts must be >= 1, got {max_attempts}')
        if initial_delay <= 0:
            raise ValueError(f'initial_delay must be > 0, got {initial_delay}')
        if max_delay < initial_delay:
            raise ValueError(
                f'max_delay ({max_delay}) must be >= initial_delay ({initial_delay})'
            )
        if exponential_base < 1.0:
            raise ValueError(f'exponential_base must be >= 1.0, got {exponential_base}')

        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.name = name
        self.logger = LogFactory().get_logger(self.__class__.__name__)

        # Track state for current execution (not shared across calls)
        self._current_attempt = 0

    def execute(
        self,
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute synchronous function with retry logic.

        Args:
            func: Synchronous function to execute.
            *args: Positional arguments for func.
            should_retry: Optional predicate to determine if exception is retryable.
                         Called with exception as argument.
                         If None, all exceptions trigger retry.
                         Return True to retry, False to raise immediately.
            **kwargs: Keyword arguments for func.

        Returns:
            Result of successful function execution.

        Raises:
            Last exception if all retry attempts exhausted.
            Exception immediately if should_retry returns False.

        Example:
            >>> def is_transient(ex):
            ...     return isinstance(ex, (TimeoutError, ConnectionError))
            >>> result = retry.execute(api_call, url="...", should_retry=is_transient)
        """
        last_exception = None
        _name = name or self.name or func.__name__

        for attempt in range(self.max_attempts):
            try:
                result = func(*args, **kwargs)

                # Reset state after success
                if attempt > 0:
                    self.logger.info(
                        f"Retry policy '{_name}' succeeded after {attempt + 1} attempts"
                    )

                return result

            except Exception as e:
                last_exception = e

                # Check if we should retry this exception
                if should_retry and not should_retry(e):
                    self.logger.debug(
                        f"Retry policy '{_name}' - exception not retryable: {type(e).__name__}"
                    )
                    raise

                # Check if we have more attempts
                if attempt + 1 >= self.max_attempts:
                    self.logger.warning(
                        f"Retry policy '{_name}' exhausted {self.max_attempts} attempts. "
                        f'Last error: {type(e).__name__}: {str(e)}'
                    )
                    raise

                # Calculate and apply delay
                delay = self.get_next_delay(attempt)
                self.logger.info(
                    f"Retry policy '{_name}' - attempt {attempt + 1}/{self.max_attempts} failed. "
                    f'Retrying in {delay:.2f}s. Error: {type(e).__name__}: {str(e)}'
                )
                time.sleep(delay)

        # Should never reach here, but for type safety
        if last_exception:
            raise last_exception
        raise RuntimeError('Retry logic error - no exception but no success')

    async def execute_async(
        self,
        # AsyncCallable = Callable[[str], Awaitable[int]]
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute asynchronous function with retry logic.

        Args:
            func: Async function to execute.
            *args: Positional arguments for func.
            should_retry: Optional predicate to determine if exception is retryable.
            **kwargs: Keyword arguments for func.

        Returns:
            Result of successful function execution.

        Raises:
            Last exception if all retry attempts exhausted.

        Example:
            >>> result = await retry.execute_async(async_api_call, url="...")
        """
        loop = asyncio.get_running_loop()
        _name = name or self.name or func.__name__

        _saved_signal_handlers: dict = {}
        _saved_asyncio_handlers: dict = {}
        if threading.current_thread() is threading.main_thread():

            def _cancel_all_on_signal():
                for task in asyncio.all_tasks(loop):
                    if not task.done():
                        task.cancel()

            for sig in (_signal.SIGINT, _signal.SIGTERM):
                try:
                    _saved_signal_handlers[sig] = _signal.getsignal(sig)
                    try:
                        existing = loop._signal_handlers.get(sig)  # type: ignore[attr-defined]
                        if existing is not None:
                            _saved_asyncio_handlers[sig] = (
                                existing._callback,
                                getattr(existing, '_args', ()),
                            )
                        else:
                            _saved_asyncio_handlers[sig] = None
                    except AttributeError:
                        _saved_asyncio_handlers[sig] = None
                    loop.add_signal_handler(sig, _cancel_all_on_signal)
                except RuntimeError, OSError, NotImplementedError:
                    _saved_signal_handlers.pop(sig, None)

        last_exception: Optional[Exception] = None
        try:
            for attempt in range(self.max_attempts):
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelled():
                    raise asyncio.CancelledError()

                try:
                    result = await func(*args, **kwargs)

                    if attempt > 0:
                        self.logger.info(
                            f"Retry policy '{_name}' succeeded after {attempt + 1} attempts"
                        )

                    return result

                except asyncio.CancelledError:
                    raise  # Never retry – always propagate cancellation
                except Exception as e:
                    last_exception = e

                    if should_retry is not None and not should_retry(e):
                        self.logger.debug(
                            f"Retry policy '{_name}' - exception not retryable: {type(e).__name__}"
                        )
                        raise

                    if attempt + 1 >= self.max_attempts:
                        self.logger.warning(
                            f"Retry policy '{_name}' exhausted {self.max_attempts} attempts. "
                            f'Last error: {type(e).__name__}: {str(e)}'
                        )
                        raise

                    delay = self.get_next_delay(attempt)
                    self.logger.info(
                        f"Retry policy '{_name}' - attempt {attempt + 1}/{self.max_attempts} failed. "
                        f'Retrying in {delay:.2f}s. Error: {type(e).__name__}: {str(e)}'
                    )
                    await asyncio.sleep(delay)
        finally:
            for sig in list(_saved_signal_handlers.keys()):
                try:
                    saved_asyncio = _saved_asyncio_handlers.get(sig)
                    if saved_asyncio is not None:
                        callback, cb_args = saved_asyncio
                        loop.add_signal_handler(sig, callback, *cb_args)
                    else:
                        loop.remove_signal_handler(sig)
                    old_handler = _saved_signal_handlers[sig]
                    if old_handler is not None:
                        _signal.signal(sig, old_handler)
                except Exception:
                    pass

        if last_exception:
            raise last_exception
        raise RuntimeError('Retry logic error - no exception but no success')

    def get_next_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry attempt.

        Uses exponential backoff: delay = initial_delay * (base ^ attempt)
        Capped at max_delay and optionally adds jitter.

        Args:
            attempt: Current attempt number (0-based).
                    0 = delay before first retry
                    1 = delay before second retry, etc.

        Returns:
            Delay in seconds before next attempt.

        Example:
            >>> retry = ExponentialBackoffRetry(initial_delay=1, base=2, max_delay=60)
            >>> retry.get_next_delay(0)  # 1.0s
            >>> retry.get_next_delay(1)  # 2.0s
            >>> retry.get_next_delay(2)  # 4.0s
            >>> retry.get_next_delay(10) # 60.0s (capped)
        """
        # Calculate exponential delay
        delay = self.initial_delay * (self.exponential_base**attempt)

        # Cap at max delay
        delay = min(delay, self.max_delay)

        # Add jitter if enabled (0-50% random variation)
        if self.jitter:
            jitter_amount = delay * random.uniform(0, 0.5)
            delay += jitter_amount

        return delay

    def reset(self) -> None:
        """
        Reset retry state to initial conditions.

        Note: This implementation is stateless per execution,
        so reset is a no-op. Included for interface compliance.
        """
        self._current_attempt = 0

    def decorator(
        self,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        name: Optional[str] = None,
    ) -> Callable:
        """
        Create a decorator for applying retry logic to functions.

        Args:
            should_retry: Optional predicate to determine if exception is retryable.
            name: Optional name for the retry instance.

        Returns:
            Decorator function.

        Example:
            >>> retry = ExponentialBackoffRetry(max_attempts=3)
            >>> @retry.decorator(should_retry=lambda e: isinstance(e, TimeoutError))
            ... def flaky_function():
            ...     return call_external_api()
        """

        def decorator_wrapper(func: Callable) -> Callable:
            if asyncio.iscoroutinefunction(func):

                @wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return await self.execute_async(
                        func, *args, should_retry=should_retry, name=name, **kwargs
                    )

                return async_wrapper
            else:

                @wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return self.execute(
                        func, *args, should_retry=should_retry, name=name, **kwargs
                    )

                return sync_wrapper

        return decorator_wrapper


class LinearBackoffRetry(IRetryPolicy):
    """
    Retry policy with fixed linear backoff.

    Uses constant delay between retries. Simpler than exponential but may
    not be optimal for distributed systems (no jitter, same timing for all clients).

    Thread-safe.

    Example:
        retry = LinearBackoffRetry(max_attempts=5, delay=2.0)
        result = retry.execute(func=risky_operation)
    """

    def __init__(
        self, max_attempts: int = 3, delay: float = 1.0, name: str = 'linear_retry'
    ):
        """
        Initialize linear retry policy.

        Args:
            max_attempts: Maximum number of attempts.
            delay: Fixed delay in seconds between retries.
            name: Name for logging.
        """
        if max_attempts < 1:
            raise ValueError(f'max_attempts must be >= 1, got {max_attempts}')
        if delay < 0:
            raise ValueError(f'delay must be >= 0, got {delay}')

        self.max_attempts = max_attempts
        self.delay = delay
        self.name = name
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    def execute(
        self,
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs: Any,
    ) -> T:
        """Execute function with linear backoff retry."""
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if should_retry and not should_retry(e):
                    raise

                if attempt + 1 >= self.max_attempts:
                    self.logger.warning(
                        f"Linear retry '{self.name}' exhausted {self.max_attempts} attempts"
                    )
                    raise

                self.logger.info(
                    f"Linear retry '{self.name}' - attempt {attempt + 1} failed, "
                    f'retrying in {self.delay}s'
                )
                time.sleep(self.delay)

        if last_exception:
            raise last_exception
        raise RuntimeError('Retry logic error')

    async def execute_async(
        self,
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs: Any,
    ) -> T:
        """Execute async function with linear backoff retry."""
        loop = asyncio.get_running_loop()

        _saved_signal_handlers: dict = {}
        _saved_asyncio_handlers: dict = {}
        if threading.current_thread() is threading.main_thread():

            def _cancel_all_on_signal():
                for task in asyncio.all_tasks(loop):
                    if not task.done():
                        task.cancel()

            for sig in (_signal.SIGINT, _signal.SIGTERM):
                try:
                    _saved_signal_handlers[sig] = _signal.getsignal(sig)
                    try:
                        existing = loop._signal_handlers.get(sig)  # type: ignore[attr-defined]
                        if existing is not None:
                            _saved_asyncio_handlers[sig] = (
                                existing._callback,
                                getattr(existing, '_args', ()),
                            )
                        else:
                            _saved_asyncio_handlers[sig] = None
                    except AttributeError:
                        _saved_asyncio_handlers[sig] = None
                    loop.add_signal_handler(sig, _cancel_all_on_signal)
                except RuntimeError, OSError, NotImplementedError:
                    _saved_signal_handlers.pop(sig, None)

        last_exception = None
        try:
            for attempt in range(self.max_attempts):
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelled():
                    raise asyncio.CancelledError()

                try:
                    return await func(*args, **kwargs)
                except asyncio.CancelledError:
                    raise  # Never retry – always propagate cancellation
                except Exception as e:
                    last_exception = e

                    if should_retry is not None and not should_retry(e):
                        raise

                    if attempt + 1 >= self.max_attempts:
                        raise

                    await asyncio.sleep(self.delay)
        finally:
            for sig in list(_saved_signal_handlers.keys()):
                try:
                    saved_asyncio = _saved_asyncio_handlers.get(sig)
                    if saved_asyncio is not None:
                        callback, cb_args = saved_asyncio
                        loop.add_signal_handler(sig, callback, *cb_args)
                    else:
                        loop.remove_signal_handler(sig)
                    old_handler = _saved_signal_handlers[sig]
                    if old_handler is not None:
                        _signal.signal(sig, old_handler)
                except Exception:
                    pass

        if last_exception:
            raise last_exception
        raise RuntimeError('Retry logic error')

    def get_next_delay(self, attempt: int) -> float:
        """Get next delay (constant for linear backoff)."""
        return self.delay

    def reset(self) -> None:
        """Reset retry state (no-op for stateless implementation)."""
        pass
