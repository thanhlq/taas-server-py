"""
Retry policy primitive.

Executes an async handler with a bounded number of attempts using a backoff
strategy (constant, exponential with optional jitter).

Layout:

* `BackoffStrategy`   - enum of supported strategies
* `RetryConfig`       - policy
* `RetryService`      - executes a handler under the policy
* `RetryFactory`      - DI helper
"""

from __future__ import annotations

import asyncio
import enum
import random
from collections.abc import Awaitable, Callable

import msgspec


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class RetryError(Exception):
    """Base class for retry errors."""


class RetryExhaustedError(RetryError):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(
            f"Retry exhausted after {attempts} attempts: {last_error!r}"
        )
        self.attempts = attempts
        self.last_error = last_error


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class BackoffStrategy(enum.StrEnum):
    CONSTANT = "constant"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class RetryConfig(msgspec.Struct, frozen=True):
    """Policy for retry execution."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.1
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.0  # 0.0 = none, 1.0 = full jitter on [0, delay]
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    # Exception types eligible for retry. Default: all `Exception`s.
    retry_on: tuple[type[BaseException], ...] = (Exception,)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class RetryService:
    """Executes an async handler with the configured retry policy."""

    def __init__(
        self,
        config: RetryConfig | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config or RetryConfig()
        self._sleep = sleep
        self._rng = rng or random.Random()

    @property
    def config(self) -> RetryConfig:
        return self._config

    async def execute[T](self, handler: Callable[[], Awaitable[T]]) -> T:
        cfg = self._config
        last_exc: BaseException | None = None
        for attempt in range(1, cfg.max_attempts + 1):
            try:
                return await handler()
            except cfg.retry_on as exc:
                last_exc = exc
                if attempt >= cfg.max_attempts:
                    break
                await self._sleep(self._compute_delay(attempt))
        assert last_exc is not None
        raise RetryExhaustedError(cfg.max_attempts, last_exc) from last_exc

    def _compute_delay(self, attempt: int) -> float:
        cfg = self._config
        match cfg.strategy:
            case BackoffStrategy.CONSTANT:
                delay = cfg.initial_delay_seconds
            case BackoffStrategy.LINEAR:
                delay = cfg.initial_delay_seconds * attempt
            case BackoffStrategy.EXPONENTIAL:
                delay = cfg.initial_delay_seconds * (cfg.multiplier ** (attempt - 1))
        delay = min(delay, cfg.max_delay_seconds)
        if cfg.jitter > 0:
            spread = delay * cfg.jitter
            delay = delay - spread + self._rng.random() * 2 * spread
            delay = max(0.0, min(delay, cfg.max_delay_seconds))
        return delay


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class RetryFactory:
    """Builds `RetryService` instances."""

    def __init__(self, config: RetryConfig | None = None) -> None:
        self._config = config

    def create_service(self, config: RetryConfig | None = None) -> RetryService:
        return RetryService(config or self._config)


__all__ = [
    "BackoffStrategy",
    "RetryConfig",
    "RetryError",
    "RetryExhaustedError",
    "RetryFactory",
    "RetryService",
]
