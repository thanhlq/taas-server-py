"""
Durable timers / schedules - contracts only (implementation: ``resiliant.schedule``,
twin of ``@taas/foundation/resiliant/schedule`` + ``@taas/resiliant/schedule``).

A job row is a persisted "wake at" time. A poller claims due rows with
``FOR UPDATE SKIP LOCKED`` and fires them, so a timer survives any number of
restarts between scheduling and firing. Jobs are created inside the caller's
transaction: "start the subscription" and "charge it in 30 days" commit together
or not at all.

A due job is delivered either to a broker channel (when ``channel`` is set) or to
the in-process callback registered under its ``job_name``. ``job_name`` is the
contract between the scheduler and that callback: keep it stable.

Kinds: ``once`` (fire at ``next_run_at``), ``interval`` (every
``interval_seconds``), ``cron`` (5-field expression, always UTC). This module
stays free of persistence imports (session / job types are ``Any``).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

import msgspec

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ScheduleError(Exception):
    """Base class for scheduler errors."""


class CronExpressionError(ScheduleError):
    """A cron expression that cannot be parsed (5 fields, UTC)."""

    def __init__(self, expression: str, reason: str) -> None:
        super().__init__(f'invalid cron expression "{expression}": {reason}')
        self.expression = expression
        self.reason = reason


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class ScheduleJobKind(enum.StrEnum):
    ONCE = 'once'
    """Fire once at ``next_run_at`` (a durable sleep)."""
    INTERVAL = 'interval'
    """Fire every ``interval_seconds``."""
    CRON = 'cron'
    """Fire on a 5-field cron expression, evaluated in UTC."""


class ScheduleJobStatus(enum.StrEnum):
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    """Claimed by a poller and firing (lease: ``claimed_at``)."""
    DONE = 'done'
    """A one-shot job that fired, or a recurring job that reached ``max_runs``."""
    FAILED = 'failed'
    """Retry budget of an occurrence exhausted."""
    CANCELLED = 'cancelled'


ACTIVE_SCHEDULE_STATES: tuple[ScheduleJobStatus, ...] = (
    ScheduleJobStatus.SCHEDULED,
    ScheduleJobStatus.RUNNING,
)

TERMINAL_SCHEDULE_STATES: frozenset[ScheduleJobStatus] = frozenset(
    {
        ScheduleJobStatus.DONE,
        ScheduleJobStatus.FAILED,
        ScheduleJobStatus.CANCELLED,
    }
)

SchedulePollStrategy = Literal['fixed', 'adaptive']


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class ScheduleConfig(msgspec.Struct, frozen=True):
    """Scheduler policy (``resolveScheduleConfig`` of the JS twin; same defaults).

    Env variables (``resiliant.schedule.schedule_settings``): ``SCHEDULE_POLL_STRATEGY``,
    ``SCHEDULE_FIXED_POLL_INTERVAL_MS``, ``SCHEDULE_MIN_POLL_INTERVAL_MS``,
    ``SCHEDULE_MAX_POLL_INTERVAL_MS``, ``SCHEDULE_BATCH_SIZE``, ``SCHEDULE_CONCURRENT_WORKERS``,
    ``SCHEDULE_MAX_RETRIES``, ``SCHEDULE_RETRY_BACKOFF_MS``, ``SCHEDULE_CLAIM_TIMEOUT_MS``
    and the Python-only ``SCHEDULE_ENABLED``.
    """

    poll_strategy: str = 'fixed'
    fixed_poll_interval_ms: int = 30_000
    min_poll_interval_ms: float = 1_000
    max_poll_interval_ms: float = 60_000
    initial_poll_interval_ms: float = 30_000
    backoff_growth_factor: float = 2.0
    drain_threshold_ratio: float = 1.0
    batch_size: int = 100
    concurrent_workers: int = 1
    max_retries: int = 3
    """Default retry budget per occurrence of a new job (``max_retries`` column)."""
    retry_backoff_ms: float = 30_000
    """Delay before a failed occurrence is fired again."""
    claim_timeout_ms: float = 300_000
    """A job RUNNING longer than this belonged to a crashed poller and is rescheduled."""
    enable_metrics: bool = True
    metrics_log_interval_ms: float = 60_000
    enabled: bool = True
    """Python only: whether a worker hosts the scheduler poller at all."""

    def __post_init__(self) -> None:
        if self.poll_strategy not in ('fixed', 'adaptive'):
            raise ValueError(
                f'schedule poll_strategy must be fixed or adaptive, got "{self.poll_strategy}"'
            )
        if self.min_poll_interval_ms > self.max_poll_interval_ms:
            raise ValueError('schedule min_poll_interval_ms cannot exceed max_poll_interval_ms')
        if not self.backoff_growth_factor > 1:
            raise ValueError(
                f'schedule backoff_growth_factor must be > 1, got {self.backoff_growth_factor}'
            )
        for key in ('batch_size', 'concurrent_workers', 'max_retries', 'fixed_poll_interval_ms'):
            value = getattr(self, key)
            if not _is_int(value) or value < 1:
                raise ValueError(f'schedule {key} must be an integer >= 1, got {value}')
        if not (isinstance(self.claim_timeout_ms, int | float) and self.claim_timeout_ms >= 1000):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime validation
            raise ValueError(f'schedule claim_timeout_ms must be >= 1000, got {self.claim_timeout_ms}')


def resolve_schedule_config(overrides: dict[str, Any] | None = None, **kwargs: Any) -> ScheduleConfig:
    """Defaults + overrides (``None`` values ignored), validated; a bad policy raises ``ValueError``."""
    merged = {**(overrides or {}), **kwargs}
    return ScheduleConfig(**{k: v for k, v in merged.items() if v is not None})


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class IScheduleRepository(Protocol):
    """Storage contract for scheduled jobs; every call runs on the caller's session."""

    async def insert(self, session: Any, **job: Any) -> Any | None: ...

    async def get(self, session: Any, job_id: int) -> Any | None: ...

    async def get_active_by_name(self, session: Any, job_name: str) -> Any | None: ...

    async def get_active_by_unique_key(self, session: Any, unique_key: str) -> Any | None: ...

    async def claim_due(self, session: Any, limit: int) -> list[Any]: ...

    async def mark_succeeded(self, session: Any, job: Any, next_run_at: datetime | None) -> bool: ...

    async def mark_failed(
        self, session: Any, job: Any, error: str, retry_at: datetime
    ) -> ScheduleJobStatus | None: ...

    async def cancel(self, session: Any, job_id: int) -> bool: ...

    async def reset_stale(self, session: Any, timeout_ms: float) -> int: ...

    async def stats(self, session: Any) -> dict[str, int]: ...


@runtime_checkable
class IScheduleService(Protocol):
    """
    Application-facing contract for durable timers / schedules.

    Every create joins the caller's session (never commits): the job row commits
    atomically with the domain write that requested it. A create returns the job,
    or ``None`` when an active job already holds ``unique_key``.
    Target keywords: ``unique_key``, ``channel``, ``event_type``, ``payload``,
    ``ordering_key``, ``headers``, ``max_retries``.
    """

    async def schedule_once(self, session: Any, *, job_name: str, run_at: datetime, **target: Any) -> Any | None:
        """Fire ``job_name`` once at ``run_at`` (a durable sleep)."""
        ...

    async def schedule_after(self, session: Any, *, job_name: str, delay_ms: float, **target: Any) -> Any | None:
        """:meth:`schedule_once` at ``now + delay_ms``."""
        ...

    async def schedule_interval(
        self,
        session: Any,
        *,
        job_name: str,
        interval_seconds: int,
        start_at: datetime | None = None,
        max_runs: int | None = None,
        **target: Any,
    ) -> Any | None:
        """Fire every ``interval_seconds``; first at ``start_at`` (default ``now + interval``)."""
        ...

    async def schedule_cron(
        self, session: Any, *, job_name: str, cron_expr: str, max_runs: int | None = None, **target: Any
    ) -> Any | None:
        """Fire on a 5-field UTC cron expression (parsed eagerly)."""
        ...

    async def cancel(self, session: Any, job_id: int) -> bool:
        """Cancel an active job; ``False`` when it was not active (idempotent)."""
        ...

    async def exists_active(self, session: Any, job_name: str) -> bool:
        """``True`` if a scheduled / running job with ``job_name`` exists."""
        ...

    async def stats(self, session: Any) -> dict[str, int]:
        """Counts per status plus ``oldest_overdue_ms``."""
        ...


__all__ = [
    'ACTIVE_SCHEDULE_STATES',
    'CronExpressionError',
    'IScheduleRepository',
    'IScheduleService',
    'ScheduleConfig',
    'ScheduleError',
    'ScheduleJobKind',
    'ScheduleJobStatus',
    'SchedulePollStrategy',
    'TERMINAL_SCHEDULE_STATES',
    'resolve_schedule_config',
]
