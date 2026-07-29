"""
Composed resilience for a single external call.

The individual guards (``TimeoutService``, ``CircuitBreakerService``,
``BulkheadService``, ``FallbackService``) each protect one failure mode. Real
outbound calls (a chain RPC, a KYC provider, a payment gateway) usually want
several at once. :class:`ResilientExecutor` stacks them from one config so call
sites write a single wrapper instead of four nested ones.

Composition (outermost → innermost)::

    fallback( circuit_breaker( bulkhead( timeout( fn ) ) ) )

Rationale for the order:

* **circuit_breaker** outermost (below fallback) so an OPEN breaker fails fast
  *before* a bulkhead slot is taken, and so timeouts propagate up and count as
  breaker failures;
* **bulkhead** next, to cap concurrency into the dependency;
* **timeout** innermost around ``fn`` so it bounds the actual call and its
  expiry surfaces as a failure to the breaker;
* **fallback** wraps everything, turning any surfaced failure into a graceful
  degradation when a fallback handler is supplied.

Usage::

    executor = ResilientExecutor(
        "kaspa-rpc",
        timeout_seconds=5.0,
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
        bulkhead=BulkheadConfig(max_concurrent=20),
        cb_repository=redis_cb_repo,          # optional: fleet-wide breaker
    )
    tip = await executor.call(lambda: client.get_tip())
    # with graceful degradation:
    tip = await executor.call(lambda: client.get_tip(), fallback=lambda exc: cached_tip)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .bulkhead import BulkheadConfig, BulkheadService
from .circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerService,
    ICircuitBreakerRepository,
)
from .fallback import FallbackConfig, FallbackService
from .timeout import TimeoutService


class ResilientExecutor:
    """Runs an async handler through a configured stack of resilience guards."""

    def __init__(
        self,
        name: str,
        *,
        timeout_seconds: float | None = None,
        circuit_breaker: CircuitBreakerConfig | None = None,
        bulkhead: BulkheadConfig | None = None,
        fallback_on: tuple[type[BaseException], ...] = (Exception,),
        cb_repository: ICircuitBreakerRepository | None = None,
    ) -> None:
        self._name = name
        self._timeout_seconds = timeout_seconds
        self._timeout = TimeoutService() if timeout_seconds is not None else None
        self._breaker = (
            CircuitBreakerService(name, circuit_breaker, repository=cb_repository)
            if circuit_breaker is not None
            else None
        )
        self._bulkhead = (
            BulkheadService(name, bulkhead) if bulkhead is not None else None
        )
        self._fallback = FallbackService(FallbackConfig(fallback_on=fallback_on))

    @property
    def name(self) -> str:
        return self._name

    @property
    def breaker(self) -> CircuitBreakerService | None:
        """The underlying breaker (exposed for snapshot/visibility)."""
        return self._breaker

    async def call[T](
        self,
        handler: Callable[[], Awaitable[T]],
        *,
        fallback: Callable[[BaseException], Awaitable[T]] | None = None,
    ) -> T:
        """Execute ``handler`` through the guard stack.

        When ``fallback`` is provided, a failure that survives the inner guards
        is routed to it instead of propagating.
        """
        primary = self._compose(handler)
        if fallback is None:
            return await primary()
        return await self._fallback.execute(primary, fallback)

    def _compose[T](
        self, handler: Callable[[], Awaitable[T]]
    ) -> Callable[[], Awaitable[T]]:
        """Wrap ``handler`` innermost→outermost: timeout, bulkhead, breaker."""
        call = handler

        if self._timeout is not None:
            inner = call
            seconds = self._timeout_seconds

            async def _with_timeout() -> T:
                return await self._timeout.execute(inner, seconds=seconds)  # type: ignore[union-attr]

            call = _with_timeout

        if self._bulkhead is not None:
            inner_bh = call

            async def _with_bulkhead() -> T:
                return await self._bulkhead.execute(inner_bh)  # type: ignore[union-attr]

            call = _with_bulkhead

        if self._breaker is not None:
            inner_cb = call

            async def _with_breaker() -> T:
                return await self._breaker.call(inner_cb)  # type: ignore[union-attr]

            call = _with_breaker

        return call


__all__ = ['ResilientExecutor']
