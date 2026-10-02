"""
One relay step over one outbox table — claim, dispatch, record the outcome, all in
ONE transaction. Same algorithm as ``OutboxProcessor`` of ``@taas/resiliant``.

Crash safety: rows are locked (``FOR UPDATE SKIP LOCKED``) while dispatched and their
outcome is written before the commit; a crash rolls the batch back and the rows are
claimable again at once. Delivery is at-least-once; consumers de-duplicate on the
event id.

Failure attribution — "this record is poison" vs "the target is down":

* while the relay's circuit is closed, a failure counts against the record's budget
  (capped exponential backoff, then ``dead_letter``);
* when ``breaker_failure_threshold`` DISTINCT records fail in a row the target is down:
  the circuit opens, the relay stops claiming for ``breaker_cooldown_ms``, then probes
  with a batch of one. Failures while open / probing do not count, so an outage never
  dead-letters records. One record failing alone never opens the circuit.

Ordering (``preserve_ordering``): after a failure the remaining records of the same
ordering key in the batch are left untouched (deferred), and the claim skips records
behind a failing one of their key.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.circuit_breaker import CircuitState
from foundation.resiliant.outbox import (
    IOutboxDispatcher,
    OutboxBatchResult,
    OutboxConfig,
    OutboxStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.sql import describe_error, exponential_backoff_ms

from .dispatchers import OutboxDispatchRouter
from .outbox_metrics import OutboxMetrics
from .outbox_repository import OutboxFailure, OutboxRepository


def _monotonic_ms() -> float:
    return time.monotonic() * 1000


class OutboxTargetCircuit:
    """closed → open (cool-down) → half-open (probe of one) → closed."""

    def __init__(
        self,
        threshold: int,
        cooldown_ms: float,
        clock: Callable[[], float] = _monotonic_ms,
    ) -> None:
        self.state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._failed_records: set[int] = set()
        self._threshold = threshold
        self._cooldown_ms = cooldown_ms
        self._clock = clock

    def admit(self) -> bool:
        """False while cooling down; moves open → half-open once the cool-down elapsed."""
        if self.state == CircuitState.OPEN:
            if self._clock() - self._opened_at < self._cooldown_ms:
                return False
            self.state = CircuitState.HALF_OPEN
        return True

    def on_success(self) -> None:
        self._failed_records.clear()
        self.state = CircuitState.CLOSED

    def on_failure(self, record_id: int) -> bool:
        """Returns whether the failure is attributed to the record."""
        attributed = self.state == CircuitState.CLOSED
        self._failed_records.add(record_id)
        if (
            self.state == CircuitState.HALF_OPEN
            or len(self._failed_records) >= self._threshold
        ):
            self.state = CircuitState.OPEN
            self._opened_at = self._clock()
        return attributed


class OutboxProcessor:
    """``process_batch()`` = one relay step; the poller loops it."""

    def __init__(
        self,
        *,
        name: str,
        repository: OutboxRepository[Any],
        session_factory: Callable[[], AsyncSession],
        dispatchers: list[IOutboxDispatcher],
        config: OutboxConfig,
        metrics: OutboxMetrics | None = None,
        clock: Callable[[], float] = _monotonic_ms,
    ) -> None:
        self.name = name
        self.repository = repository
        self.session_factory = session_factory
        self.router = OutboxDispatchRouter(dispatchers)
        self.config = config
        self.metrics = (
            metrics
            if metrics is not None
            else (OutboxMetrics() if config.enable_metrics else None)
        )
        self.circuit = OutboxTargetCircuit(
            config.breaker_failure_threshold, config.breaker_cooldown_ms, clock
        )
        self._clock = clock
        self.logger = LogFactory().get_logger(f'OutboxProcessor[{name}]')

    @property
    def circuit_state(self) -> str:
        return self.circuit.state.value

    async def process_batch(self) -> OutboxBatchResult:
        if not self.circuit.admit():
            return OutboxBatchResult(circuit=self.circuit.state.value)
        limit = (
            1
            if self.circuit.state == CircuitState.HALF_OPEN
            else self.config.batch_size
        )
        started = self._clock()
        try:
            async with self.session_factory() as session, session.begin():
                result = await self._run(session, limit)
        except Exception:
            if self.metrics:
                self.metrics.record_poll(
                    duration_ms=self._clock() - started, batch_size=0, success=False
                )
            raise
        if self.metrics:
            self.metrics.record_poll(
                duration_ms=self._clock() - started,
                batch_size=result.claimed,
                success=True,
            )
        return result

    async def _run(self, session: AsyncSession, limit: int) -> OutboxBatchResult:
        cfg = self.config
        repository = self.repository
        records = await repository.claim(
            session, limit, preserve_ordering=cfg.preserve_ordering
        )
        published: list[int] = []
        failures: list[OutboxFailure] = []
        blocked_keys: set[str] = set()
        deferred = 0

        for record in records:
            if self.circuit.state == CircuitState.OPEN:
                deferred += 1  # the target went down mid-batch: the rest waits for the cool-down
                continue
            if (
                cfg.preserve_ordering
                and record.ordering_key is not None
                and record.ordering_key in blocked_keys
            ):
                deferred += 1
                continue
            started = self._clock()
            try:
                await asyncio.wait_for(
                    self.router.dispatch(record), timeout=cfg.dispatch_timeout_ms / 1000
                )
                published.append(record.id)
                self.circuit.on_success()
                duration = self._clock() - started
                if self.metrics:
                    self.metrics.record_publish(duration_ms=duration, success=True)
                # Wording relied on by tests/e2e/user-registration ("healthy run").
                self.logger.debug(
                    f'Published event {record.event_type} (id={record.id}) to {record.channel} in {duration:.2f}ms'
                )
            except Exception as error:  # noqa: BLE001 - every failure is recorded on the row
                counted = self.circuit.on_failure(record.id)
                attempt = (
                    record.retry_count + 1 if counted else max(record.retry_count, 1)
                )
                message = (
                    f'timeout: dispatch of {record.event_type}'
                    if isinstance(error, TimeoutError)
                    else describe_error(error)
                )
                failures.append(
                    OutboxFailure(
                        record=record,
                        error=message,
                        counted=counted,
                        retry_in_ms=exponential_backoff_ms(
                            attempt,
                            cfg.retry_backoff_multiplier,
                            cfg.retry_max_backoff_ms,
                        ),
                    )
                )
                if record.ordering_key is not None:
                    blocked_keys.add(record.ordering_key)

        await repository.mark_published(session, published)
        dead_lettered = 0
        for failure in failures:
            status = await repository.mark_failed(session, failure)
            dead = status == OutboxStatus.DEAD_LETTER
            dead_lettered += int(dead)
            if self.metrics:
                self.metrics.record_publish(
                    duration_ms=0, success=False, moved_to_dlq=dead
                )
            record = failure.record
            if dead:
                how = f'dead-lettered after {record.retry_count + 1} attempts'
            elif failure.counted:
                how = f'attempt {record.retry_count + 1}/{record.max_retries}, retry in {failure.retry_in_ms:.0f}ms'
            else:
                how = f'target unavailable (not counted), retry in {failure.retry_in_ms:.0f}ms'
            log = self.logger.error if dead else self.logger.warning
            log(
                f'{repository.table_name} #{record.id} {record.event_type} {how}: {failure.error}'
            )
        if self.circuit.state == CircuitState.OPEN and failures:
            self.logger.warning(
                f'{repository.table_name}: target looks down ({len(failures)} failures), pausing {cfg.breaker_cooldown_ms}ms'
            )
        return OutboxBatchResult(
            claimed=len(records),
            published=len(published),
            failed=len(failures),
            dead_lettered=dead_lettered,
            deferred=deferred,
            circuit=self.circuit.state.value,
        )

    async def stats(self, *, exact_published: bool = False) -> dict[str, Any]:
        async with self.session_factory() as session:
            stats = await self.repository.stats(
                session, exact_published=exact_published
            )
        return {'outbox': self.name, 'table': self.repository.table_name, **stats}


__all__ = ['OutboxProcessor', 'OutboxTargetCircuit']
