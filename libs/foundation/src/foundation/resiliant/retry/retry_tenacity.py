"""
Tenacity-based retry implementation.

Simple wrapper around the battle-tested Tenacity library for retry logic.
Provides a clean interface while leveraging Tenacity's robust retry mechanisms.
"""

import asyncio
import signal as _signal
import threading
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    Retrying,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
)

from ...observability.log_factory import LogFactory
from ..types import IRetryPolicy

T = TypeVar('T')


class TenacityRetry(IRetryPolicy):
    """
    Retry policy wrapper for Tenacity library - production-ready implementation.

    Provides a clean interface to Tenacity's battle-tested retry functionality.
    Tenacity is a mature, production-ready library with extensive features,
    excellent stability, and widespread adoption.

    Implements exponential backoff: delay = initial_delay * multiplier * (base ^ attempt)
    Or fixed backoff: constant delay between retries.

    Thread-safe: Tenacity handles concurrency internally.

    **Comparison with ExponentialBackoffRetry:**
    - TenacityRetry: Uses battle-tested Tenacity library, more features, production-proven
    - ExponentialBackoffRetry: Lightweight native implementation, supports jitter, fewer dependencies

    Choose TenacityRetry for:
        - Production systems requiring proven reliability
        - Complex retry scenarios with advanced conditions
        - Enterprise applications with strict stability requirements

    Choose ExponentialBackoffRetry for:
        - Lightweight applications with minimal dependencies
        - Custom jitter requirements (0-50% randomization)
        - Educational purposes or simple retry needs

    Use cases:
        - External API calls with rate limiting
        - Database connection failures
        - Distributed system communication
        - Microservice-to-microservice calls

    Example:
        # Exponential backoff for API calls
        retry = TenacityRetry(
            max_attempts=5,
            initial_delay=1.0,
            max_delay=60.0,
            exponential_base=2.0
        )

        # Async execution
        result = await retry.execute_async(
            func=async_api_call,
            url="https://api.example.com",
            should_retry=lambda ex: isinstance(ex, TimeoutError)
        )

        # Sync execution
        result = retry.execute(
            func=call_database,
            query="SELECT * FROM users"
        )

        # As decorator
        @retry.decorator()
        async def fetch_data():
            return await api.get()

        # Fixed delay for predictable retries
        retry_fixed = TenacityRetry(
            max_attempts=3,
            initial_delay=2.0,
            wait_strategy='fixed'
        )
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        name: str = 'tenacity_retry',
        # Additional parameters specific to TenacityRetry
        wait_strategy: str = 'exponential',
        exponential_multiplier: float = 1.0,
        retry_on_exceptions: Optional[tuple] = None,
    ):
        """
        Initialize Tenacity-based retry policy.

        Args:
            max_attempts: Maximum number of attempts (including initial attempt).
                         Must be >= 1. Default: 3
            initial_delay: Initial delay in seconds before first retry.
                          Must be > 0. Default: 1.0
                          For 'fixed' strategy, this is the constant delay.
            max_delay: Maximum delay in seconds between retries.
                      Must be >= initial_delay. Default: 60.0
                      Only applies to 'exponential' strategy.
            exponential_base: Base for exponential backoff calculation.
                             Common values: 2.0 (double each time), 1.5, 3.0.
                             Must be >= 1.0. Default: 2.0
                             Formula: delay = initial_delay * multiplier * (base ^ attempt)
            jitter: Jitter flag (for ExponentialBackoffRetry compatibility).
                   Ignored by TenacityRetry (Tenacity uses deterministic delays).
                   Default: True
            name: Name for logging purposes. Default: "tenacity_retry"
            wait_strategy: Backoff strategy: 'exponential' or 'fixed'.
                          Default: 'exponential'
                          - 'exponential': Delay increases exponentially
                          - 'fixed': Constant delay between retries
            exponential_multiplier: Multiplier for exponential backoff calculation.
                                   Default: 1.0
                                   Allows fine-tuning: delay = initial * multiplier * (base ^ attempt)
            retry_on_exceptions: Tuple of exception types to retry on.
                                If None, retries on all exceptions. Default: None
                                Example: (TimeoutError, ConnectionError)

        Raises:
            ValueError: If parameters are invalid.

        Note:
            The jitter parameter is accepted for API compatibility with
            ExponentialBackoffRetry but is not used by Tenacity (which uses
            deterministic delays). Use ExponentialBackoffRetry if you need jitter.

        Example:
            >>> # Can use identical constructor for both implementations
            >>> retry = TenacityRetry(
            ...     max_attempts=5,
            ...     initial_delay=1.0,
            ...     max_delay=60.0,
            ...     exponential_base=2.0,
            ...     jitter=True  # Accepted but ignored
            ... )
        """
        # Validate parameters (consistent with ExponentialBackoffRetry)
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
        if wait_strategy not in ('exponential', 'fixed'):
            raise ValueError(
                f"wait_strategy must be 'exponential' or 'fixed', got {wait_strategy}"
            )

        # Store parameters in consistent order (jitter ignored for Tenacity)
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter  # Stored but not used (for API compatibility)
        self.wait_strategy = wait_strategy
        self.exponential_multiplier = exponential_multiplier
        self.retry_on_exceptions = retry_on_exceptions or (Exception,)
        self.name = name
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    def _create_wait_strategy(self):
        """Create Tenacity wait strategy based on configuration."""
        if self.wait_strategy == 'exponential':
            return wait_exponential(
                multiplier=self.exponential_multiplier,
                min=self.initial_delay,
                max=self.max_delay,
                exp_base=self.exponential_base,
            )
        else:  # fixed
            return wait_fixed(self.initial_delay)

    def _create_retry_condition(
        self, should_retry: Optional[Callable[[Exception], bool]] = None
    ):
        """Create Tenacity retry condition (used for the sync Tenacity path only)."""
        if should_retry is not None:

            def custom_retry(retry_state):
                if retry_state.outcome.failed:
                    exception = retry_state.outcome.exception()
                    # Never retry OS-level signals
                    if isinstance(exception, (KeyboardInterrupt, SystemExit)):
                        return False
                    return should_retry(exception)
                return False

            return custom_retry
        else:
            # Exception-only (excludes BaseException subtypes like KeyboardInterrupt)
            return retry_if_exception_type(self.retry_on_exceptions)

    def execute(
        self,
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute synchronous function with retry logic using Tenacity.

        Args:
            func: Synchronous function to execute.
            *args: Positional arguments for func.
            should_retry: Optional predicate to determine if exception is retryable.
                         Called with exception as argument.
                         If None, retries on exceptions in retry_on_exceptions.
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
        retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=self._create_wait_strategy(),
            retry=self._create_retry_condition(should_retry),
            reraise=True,
            before_sleep=lambda retry_state: self.logger.info(
                f"Retry '{self.name}' - attempt {retry_state.attempt_number}/{self.max_attempts} "
                f'failed, retrying in {retry_state.next_action.sleep}s'
            ),
        )

        try:
            return retryer(func, *args, **kwargs)
        except RetryError as e:
            # Extract the original exception from RetryError
            if e.last_attempt.failed:
                e.reraise()  # This will raise the original exception that caused the failure
                # raise e.last_attempt.exception()
            raise

    async def execute_async(
        self,
        func: Callable[..., T],
        *args: Any,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute asynchronous function with retry logic using Tenacity.

        Args:
            func: Async function to execute.
            *args: Positional arguments for func.
            should_retry: Optional predicate to determine if exception is retryable.
                         Called with exception as argument.
                         If None, retries on exceptions in retry_on_exceptions.
                         Return True to retry, False to raise immediately.
            **kwargs: Keyword arguments for func.

        Returns:
            Result of successful function execution.

        Raises:
            Last exception if all retry attempts exhausted.
            Exception immediately if should_retry returns False.

        Example:
            >>> async def is_transient(ex):
            ...     return isinstance(ex, (TimeoutError, ConnectionError))
            >>> result = await retry.execute_async(async_api, should_retry=is_transient)
        """
        # NOTE: We do NOT use Tenacity's AsyncRetrying here.
        # AsyncRetrying uses `except BaseException:` internally, which catches
        # asyncio.CancelledError (a BaseException in Python 3.8+). Even when our
        # condition returns False, Tenacity re-raises via a new exception instance
        # which breaks asyncio's task-cancellation protocol.
        #
        # Instead we use a plain loop with:
        #   1. `except asyncio.CancelledError: raise` – never retry a cancelled task
        #   2. `loop.add_signal_handler` – same pattern as worker.py's
        #      setup_signal_handlers(), so Ctrl+C cancels THIS task directly even
        #      when the outer framework (uvicorn, worker) hasn't cancelled it yet.

        loop = asyncio.get_running_loop()
        _current_task = asyncio.current_task()

        # Install asyncio-level SIGINT/SIGTERM handlers (worker.py pattern).
        # These run inside the event loop, so they can safely call task.cancel().
        # They work alongside signal.signal-based handlers (e.g. uvicorn's handle_exit)
        # because Python's set_wakeup_fd mechanism is independent.
        #
        # We cancel ALL running tasks (not just the current one) because:
        # - In uvicorn: execute_async runs inside a background lifespan task, but
        #   the server task is blocked on startup_event.wait(). We must cancel it too.
        # - In the worker: same pattern as worker.py's handle_shutdown fix.
        # We save/restore the previous signal.signal handler (e.g. uvicorn's handle_exit)
        # using signal.getsignal so we don't permanently break the outer handler.
        _saved_signal_handlers: dict = {}
        _saved_asyncio_handlers: dict = {}
        if threading.current_thread() is threading.main_thread():

            def _cancel_all_on_signal():
                for task in asyncio.all_tasks(loop):
                    if not task.done():
                        task.cancel()

            for sig in (_signal.SIGINT, _signal.SIGTERM):
                try:
                    # Save the current thread-level signal handler (e.g. uvicorn's handle_exit).
                    _saved_signal_handlers[sig] = _signal.getsignal(sig)

                    # Optionally save any existing asyncio-level handler.
                    # _signal_handlers is a CPython/asyncio internal dict; uvloop and other
                    # loop implementations don't expose it, so we guard with a nested try.
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
                        # uvloop and others: no _signal_handlers. Skip asyncio-level save.
                        _saved_asyncio_handlers[sig] = None

                    # Always install our handler — both asyncio.SelectorEventLoop and
                    # uvloop.Loop support loop.add_signal_handler().
                    loop.add_signal_handler(sig, _cancel_all_on_signal)
                except RuntimeError, OSError, NotImplementedError:
                    # Can't install (non-Unix, events loop not running, etc.)
                    _saved_signal_handlers.pop(sig, None)

        last_exception: Optional[Exception] = None
        try:
            for attempt in range(self.max_attempts):
                # Check if task was cancelled between attempts (e.g. CancelledError
                # swallowed inside a third-party coroutine like aiokafka).
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelled():
                    raise asyncio.CancelledError()

                try:
                    result = await func(*args, **kwargs)
                    if attempt > 0:
                        self.logger.info(
                            f"Retry '{self.name}' succeeded after {attempt + 1} attempts"
                        )
                    return result
                except asyncio.CancelledError:
                    raise  # Never retry – always propagate cancellation
                except Exception as e:
                    last_exception = e

                    if should_retry is not None and not should_retry(e):
                        raise

                    if attempt + 1 >= self.max_attempts:
                        self.logger.warning(
                            f"Retry '{self.name}' exhausted {self.max_attempts} attempts. "
                            f'Last error: {type(e).__name__}: {str(e)}'
                        )
                        raise

                    delay = self.get_next_delay(attempt)
                    self.logger.info(
                        f"🔁 Retry '{self.name}' - attempt {attempt + 1}/{self.max_attempts} failed. "
                        f'Retrying in {delay:.2f}s. Error: {type(e).__name__}: {str(e)}'
                    )
                    # CancelledError raised here (from our signal handler) propagates up.
                    await asyncio.sleep(delay)
        finally:
            # Restore previous signal handlers so the caller's handlers are intact.
            for sig in list(_saved_signal_handlers.keys()):
                try:
                    # Restore asyncio-level handler
                    saved_asyncio = _saved_asyncio_handlers.get(sig)
                    if saved_asyncio is not None:
                        callback, cb_args = saved_asyncio
                        loop.add_signal_handler(sig, callback, *cb_args)
                    else:
                        loop.remove_signal_handler(sig)
                    # Restore thread-level signal handler (e.g. uvicorn's handle_exit)
                    old_handler = _saved_signal_handlers[sig]
                    if old_handler is not None:
                        _signal.signal(sig, old_handler)
                except Exception:
                    pass

        if last_exception:
            raise last_exception
        raise RuntimeError('Retry logic error – no exception but no success')

    def get_next_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry attempt.

        For exponential: delay = initial_delay * multiplier * (base ^ attempt), capped at max_delay
        For fixed: returns initial_delay constant

        Args:
            attempt: Current attempt number (0-based).
                    0 = delay before first retry
                    1 = delay before second retry, etc.

        Returns:
            Delay in seconds before next attempt.

        Example:
            >>> retry = TenacityRetry(initial_delay=1, exponential_base=2, max_delay=60)
            >>> retry.get_next_delay(0)  # 1.0s
            >>> retry.get_next_delay(1)  # 2.0s
            >>> retry.get_next_delay(2)  # 4.0s
            >>> retry.get_next_delay(10) # 60.0s (capped)
        """
        if self.wait_strategy == 'exponential':
            delay = (
                self.initial_delay
                * self.exponential_multiplier
                * (self.exponential_base**attempt)
            )
            return min(delay, self.max_delay)
        else:
            return self.initial_delay

    def reset(self) -> None:
        """
        Reset retry state to initial conditions.

        Note: Tenacity is stateless per execution (each execute() call is independent),
        so reset is a no-op. Included for IRetryPolicy interface compliance.
        This matches the stateless design of ExponentialBackoffRetry.
        """
        pass

    def decorator(
        self,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        name: Optional[str] = None,
    ) -> Callable:
        """
        Create a decorator for applying retry logic to functions.

        Args:
            should_retry: Optional predicate to determine if exception is retryable.

        Returns:
            Decorator function.

        Example:
            >>> retry = TenacityRetry(max_attempts=3)
            >>> @retry.decorator()
            ... async def fetch_data():
            ...     return await api.get()
        """

        def decorator_wrapper(func: Callable) -> Callable:
            # Async functions go through execute_async which uses a plain loop
            # with `except asyncio.CancelledError: raise` and loop.add_signal_handler
            # (worker.py pattern). CancelledError (BaseException) is never swallowed.
            if asyncio.iscoroutinefunction(func):

                @wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return await self.execute_async(
                        func, *args, should_retry=should_retry, **kwargs
                    )

                return async_wrapper

            # Sync functions use Tenacity's built-in decorator (safe for sync).
            _name = name or self.name or func.__name__
            retry_decorator = retry(
                stop=stop_after_attempt(self.max_attempts),
                wait=self._create_wait_strategy(),
                retry=self._create_retry_condition(should_retry),
                reraise=True,
                before_sleep=lambda retry_state: self.logger.info(
                    f"🔁 Retry '{_name}' - attempt {retry_state.attempt_number}/{self.max_attempts} "
                    f'failed, retrying in {retry_state.next_action.sleep}s'
                ),
            )
            return retry_decorator(func)

        return decorator_wrapper


# Convenience alias
RetryTenacity = TenacityRetry
