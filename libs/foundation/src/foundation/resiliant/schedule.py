"""
Durable timer / scheduler primitive.

This is the Temporal-equivalent of *durable timers* (``workflow.sleep(...)``)
and *schedules / cron*. A "wake at" timestamp is persisted to the database and a
polling relay (see :class:`resiliant.schedule.SchedulerPoller`) fires the job
when it is due. Because the state lives in Postgres, a job survives any number
of worker restarts between scheduling and firing — the defining property of a
*durable* timer.

Three job kinds are supported:

* ``ONCE``     - fire exactly once at ``next_run_at`` (durable ``sleep``).
* ``INTERVAL`` - fire every ``interval_seconds`` (simple recurring timer).
* ``CRON``     - fire on a cron expression (requires the optional ``croniter``
  dependency; only needed when a ``CRON`` job is actually scheduled).

Layout mirrors the other resiliant primitives:

* ``ScheduleJobKind``   - the recurrence type of a job
* ``ScheduleJobStatus`` - lifecycle state of a scheduled job
* ``ScheduleConfig``    - polling / retry policy
* ``IScheduleRepository`` - pluggable storage protocol
* ``IScheduleService``  - application-facing scheduling API
* ``ScheduleError``     - base error type

The database-backed implementation lives in the ``resiliant`` library and the
SQLAlchemy model in ``db.models.resiliant``; this module stays free of
persistence-layer imports (session/return types are intentionally ``Any``).
"""

from __future__ import annotations

import enum
from typing import Any, Protocol, runtime_checkable

import msgspec

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ScheduleError(Exception):
    """Base class for scheduler errors."""


class CronSupportError(ScheduleError):
    """Raised when a CRON job is used but the ``croniter`` dependency is absent."""


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class ScheduleJobKind(enum.StrEnum):
    ONCE = 'once'
    INTERVAL = 'interval'
    CRON = 'cron'


class ScheduleJobStatus(enum.StrEnum):
    SCHEDULED = 'scheduled'
    """Waiting for ``next_run_at`` to arrive."""
    RUNNING = 'running'
    """Claimed by a poller worker and currently firing."""
    DONE = 'done'
    """A ONCE job that fired successfully (terminal)."""
    FAILED = 'failed'
    """Retry budget exhausted (terminal until an operator re-enables it)."""
    CANCELLED = 'cancelled'
    """Cancelled by an operator/caller (terminal)."""


TERMINAL_SCHEDULE_STATES: frozenset[ScheduleJobStatus] = frozenset(
    {
        ScheduleJobStatus.DONE,
        ScheduleJobStatus.FAILED,
        ScheduleJobStatus.CANCELLED,
    }
)


class ScheduleConfig(msgspec.Struct, frozen=True):
    """Policy for the scheduler poller.

    A day-scale business timer does not need sub-second precision, so the
    defaults poll far less aggressively than the outbox relay.
    """

    enabled: bool = True

    # Poll strategy: 'fixed' sleeps a constant interval; 'adaptive' backs off
    # (decorrelated jitter) when idle and speeds up when work is found.
    poll_strategy: str = 'fixed'

    fixed_poll_interval_ms: int = 30_000
    min_poll_interval_ms: int = 1_000
    max_poll_interval_ms: int = 60_000
    initial_poll_interval_ms: int = 30_000
    backoff_growth_factor: float = 2.0
    drain_threshold_ratio: float = 1.0

    # Batch / concurrency
    batch_size: int = 100
    concurrent_workers: int = 1

    # Retry policy for a job whose dispatch raised.
    max_retries: int = 3
    retry_backoff_seconds: float = 30.0

    # Reclaim jobs stuck in RUNNING (crashed worker) after this many seconds.
    claim_timeout_seconds: int = 300

    # Database
    use_skip_locked: bool = True

    # Monitoring
    enable_metrics: bool = True
    metrics_log_interval_seconds: int = 60

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError(f'batch_size must be >= 1, got {self.batch_size}')
        if self.concurrent_workers < 1:
            raise ValueError(
                f'concurrent_workers must be >= 1, got {self.concurrent_workers}'
            )
        if self.poll_strategy not in ('fixed', 'adaptive'):
            raise ValueError(
                f"poll_strategy must be 'fixed' or 'adaptive', "
                f'got {self.poll_strategy!r}'
            )
        if self.min_poll_interval_ms > self.max_poll_interval_ms:
            raise ValueError(
                'min_poll_interval_ms cannot exceed max_poll_interval_ms'
            )
        if self.backoff_growth_factor <= 1.0:
            raise ValueError(
                f'backoff_growth_factor must be > 1.0, got {self.backoff_growth_factor}'
            )


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class IScheduleRepository(Protocol):
    """Storage contract for scheduled jobs (database-backed in production)."""

    async def save(self, session: Any, job: Any) -> Any: ...

    async def fetch_due_batch(
        self, session: Any, batch_size: int | None = None
    ) -> list[Any]: ...

    async def mark_succeeded(
        self, session: Any, job_id: str, *, next_run_at: Any | None
    ) -> None: ...

    async def mark_failed(
        self, session: Any, job_id: str, error: str, *, next_run_at: Any | None
    ) -> None: ...

    async def cancel(self, session: Any, job_id: str) -> None: ...

    async def reset_stale_running(
        self, session: Any, timeout_seconds: int | None = None
    ) -> int: ...

    async def get_stats(self, session: Any) -> dict[str, Any]: ...


@runtime_checkable
class IScheduleService(Protocol):
    """
    Application-facing contract for durable timers / schedules.

    Callers use these inside their own business transaction so the job row
    commits atomically with the domain write that requested it. Session/return
    types are ``Any`` so this definitions module stays persistence-agnostic.
    """

    async def schedule_once(
        self,
        session: Any,
        *,
        job_name: str,
        run_at: Any,
        channel: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Fire ``job_name`` exactly once at ``run_at`` (a durable sleep)."""
        ...

    async def schedule_after(
        self,
        session: Any,
        *,
        job_name: str,
        delay_seconds: float,
        **kwargs: Any,
    ) -> Any:
        """Convenience: :meth:`schedule_once` at ``now + delay_seconds``."""
        ...

    async def schedule_interval(
        self,
        session: Any,
        *,
        job_name: str,
        interval_seconds: int,
        start_at: Any | None = None,
        max_runs: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Fire every ``interval_seconds`` (recurring timer)."""
        ...

    async def schedule_cron(
        self,
        session: Any,
        *,
        job_name: str,
        cron_expr: str,
        max_runs: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Fire on a cron expression (needs the ``croniter`` dependency)."""
        ...

    async def cancel(self, session: Any, job_id: str) -> None:
        """Cancel a pending job."""
        ...

    async def exists_active(self, session: Any, job_name: str) -> bool:
        """Return ``True`` if a non-terminal job with ``job_name`` exists."""
        ...

    async def get_stats(self, session: Any) -> dict[str, Any]:
        """Return counters describing the scheduler backlog."""
        ...


__all__ = [
    'CronSupportError',
    'IScheduleRepository',
    'IScheduleService',
    'ScheduleConfig',
    'ScheduleError',
    'ScheduleJobKind',
    'ScheduleJobStatus',
    'TERMINAL_SCHEDULE_STATES',
]
