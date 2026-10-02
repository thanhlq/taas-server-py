"""
Scheduled-job repository (port of ``@taas/resiliant`` ``schedule/repository.ts``).

Every method runs on the caller's session and never commits: a create or a cancel
joins the business transaction; the poller owns the transactions of its steps.

Claiming is a lease: due rows move to RUNNING with ``claimed_at`` and the claim
commits before the job fires (a callback may run for minutes and must not hold row
locks). ``FOR UPDATE SKIP LOCKED`` in the claim means two pollers never fire the
same occurrence; :meth:`ScheduleRepository.reset_stale` reschedules the jobs of a
crashed poller. Outcomes are compare-and-set on RUNNING, so a job cancelled while
it fired stays cancelled. Status predicates are inlined literals (``in_values``)
matching the partial indexes; timestamps come from the database clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from foundation.resiliant.schedule import (
    ACTIVE_SCHEDULE_STATES,
    ScheduleConfig,
    ScheduleJobKind,
    ScheduleJobStatus,
)
from sqlalchemy import BigInteger, CursorResult, Integer, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import ScheduledJobTable
from resiliant.sql import clip, db_now, db_now_minus_ms, in_values

_T = ScheduledJobTable
_SCHEDULED = (ScheduleJobStatus.SCHEDULED,)
_RUNNING = (ScheduleJobStatus.RUNNING,)
# Plain UPDATEs: no ORM session synchronisation (the predicates are not evaluable in Python).
_NO_SYNC = {'synchronize_session': False}


def _row_count(result: Any) -> int:
    return result.rowcount if isinstance(result, CursorResult) else 0


class ScheduleRepository:
    """Scheduled-job storage on the ``resiliant_scheduled_jobs`` table."""

    def __init__(self, config: ScheduleConfig | None = None) -> None:
        # Kept for the builders' signature; the repository itself needs no policy.
        self.config = config

    async def insert(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        kind: ScheduleJobKind,
        next_run_at: datetime,
        max_retries: int,
        unique_key: str | None = None,
        cron_expr: str | None = None,
        interval_seconds: int | None = None,
        channel: str | None = None,
        event_type: str | None = None,
        ordering_key: str | None = None,
        payload: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        max_runs: int | None = None,
    ) -> ScheduledJobTable | None:
        """The new job, or ``None`` when an active job already holds ``unique_key``."""
        stmt = (
            pg_insert(_T)
            .values(
                job_name=job_name,
                unique_key=unique_key,
                kind=kind,
                cron_expr=cron_expr,
                interval_seconds=interval_seconds,
                channel=channel,
                event_type=event_type,
                ordering_key=ordering_key,
                payload=payload if payload is not None else {},
                headers=headers,
                next_run_at=next_run_at,
                max_runs=max_runs,
                max_retries=max_retries,
            )
            .on_conflict_do_nothing(
                index_elements=[_T.unique_key],
                index_where=_T.unique_key.is_not(None) & in_values(_T.status, ACTIVE_SCHEDULE_STATES),
            )
            .returning(_T)
        )
        return (await session.scalars(stmt)).one_or_none()

    async def get(self, session: AsyncSession, job_id: int) -> ScheduledJobTable | None:
        stmt = select(_T).where(_T.id == job_id).limit(1).execution_options(populate_existing=True)
        return (await session.scalars(stmt)).one_or_none()

    async def get_active_by_name(self, session: AsyncSession, job_name: str) -> ScheduledJobTable | None:
        stmt = (
            select(_T)
            .where(_T.job_name == job_name, in_values(_T.status, ACTIVE_SCHEDULE_STATES))
            .order_by(_T.id.asc())
            .limit(1)
        )
        return (await session.scalars(stmt)).one_or_none()

    async def get_active_by_unique_key(
        self, session: AsyncSession, unique_key: str
    ) -> ScheduledJobTable | None:
        stmt = (
            select(_T)
            .where(_T.unique_key == unique_key, in_values(_T.status, ACTIVE_SCHEDULE_STATES))
            .limit(1)
        )
        return (await session.scalars(stmt)).one_or_none()

    async def claim_due(self, session: AsyncSession, limit: int) -> list[ScheduledJobTable]:
        """Lease up to ``limit`` due jobs (SCHEDULED, ``next_run_at <= now()``), oldest due first.

        Must run in a transaction the caller commits right after (row locks).
        """
        due = (
            select(_T.id)
            .where(in_values(_T.status, _SCHEDULED), _T.next_run_at <= db_now())
            .order_by(_T.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(_T)
            .where(_T.id.in_(due.scalar_subquery()), in_values(_T.status, _SCHEDULED))
            .values(status=ScheduleJobStatus.RUNNING, claimed_at=db_now(), updated_at=db_now())
            .returning(_T)
            .execution_options(populate_existing=True, **_NO_SYNC)
        )
        jobs = list((await session.scalars(stmt)).all())
        return sorted(jobs, key=lambda job: job.next_run_at)

    async def mark_succeeded(
        self, session: AsyncSession, job: ScheduledJobTable, next_run_at: datetime | None
    ) -> bool:
        """A successful fire: next occurrence, or DONE (one-shot, or ``max_runs`` reached)."""
        run_count = job.run_count + 1
        done = next_run_at is None or (job.max_runs is not None and run_count >= job.max_runs)
        stmt = (
            update(_T)
            .where(_T.id == job.id, in_values(_T.status, _RUNNING))
            .values(
                status=ScheduleJobStatus.DONE if done else ScheduleJobStatus.SCHEDULED,
                next_run_at=job.next_run_at if done else next_run_at,
                last_run_at=db_now(),
                claimed_at=None,
                run_count=run_count,
                attempts=0,
                last_error=None,
                updated_at=db_now(),
            )
            .execution_options(**_NO_SYNC)
        )
        return _row_count(await session.execute(stmt)) == 1

    async def mark_failed(
        self, session: AsyncSession, job: ScheduledJobTable, error: str, retry_at: datetime
    ) -> ScheduleJobStatus | None:
        """A failed fire: retry the same occurrence at ``retry_at``, or FAILED when the budget is spent.

        Returns the new status, or ``None`` when the job was no longer RUNNING (e.g. cancelled).
        """
        attempts = job.attempts + 1
        exhausted = attempts >= job.max_retries
        status = ScheduleJobStatus.FAILED if exhausted else ScheduleJobStatus.SCHEDULED
        stmt = (
            update(_T)
            .where(_T.id == job.id, in_values(_T.status, _RUNNING))
            .values(
                status=status,
                next_run_at=job.next_run_at if exhausted else retry_at,
                claimed_at=None,
                attempts=attempts,
                last_error=clip(error),
                updated_at=db_now(),
            )
            .execution_options(**_NO_SYNC)
        )
        return status if _row_count(await session.execute(stmt)) == 1 else None

    async def cancel(self, session: AsyncSession, job_id: int) -> bool:
        """Idempotent; only affects active jobs."""
        stmt = (
            update(_T)
            .where(_T.id == job_id, in_values(_T.status, ACTIVE_SCHEDULE_STATES))
            .values(status=ScheduleJobStatus.CANCELLED, claimed_at=None, updated_at=db_now())
            .execution_options(**_NO_SYNC)
        )
        return _row_count(await session.execute(stmt)) == 1

    async def reset_stale(self, session: AsyncSession, timeout_ms: float) -> int:
        """Jobs RUNNING for longer than ``timeout_ms`` belonged to a crashed poller: schedule them again."""
        stmt = (
            update(_T)
            .where(in_values(_T.status, _RUNNING), _T.claimed_at < db_now_minus_ms(timeout_ms))
            .values(status=ScheduleJobStatus.SCHEDULED, claimed_at=None, updated_at=db_now())
            .execution_options(**_NO_SYNC)
        )
        return _row_count(await session.execute(stmt))

    async def stats(self, session: AsyncSession) -> dict[str, int]:
        """Counts per status plus ``oldest_overdue_ms`` (age of the oldest due SCHEDULED job)."""
        stats: dict[str, int] = {status.value: 0 for status in ScheduleJobStatus}
        stats['oldest_overdue_ms'] = 0
        rows = await session.execute(
            select(_T.status, cast(func.count(), Integer)).group_by(_T.status)
        )
        for status, count in rows.all():
            stats[str(getattr(status, 'value', status))] = int(count)
        overdue_ms = cast(func.extract('epoch', db_now() - func.min(_T.next_run_at)) * 1000, BigInteger)
        overdue = await session.scalar(
            select(overdue_ms)
            .select_from(_T)
            .where(in_values(_T.status, _SCHEDULED), _T.next_run_at <= db_now())
        )
        stats['oldest_overdue_ms'] = 0 if overdue is None else max(0, int(overdue))
        return stats


__all__ = ['ScheduleRepository']
