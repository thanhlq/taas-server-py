"""
Scheduled-job repository (database operations for durable timers).

All methods operate on a caller-supplied :class:`AsyncSession`. The claim query
uses ``FOR UPDATE SKIP LOCKED`` so multiple poller workers never fire the same
job — the same single-owner guarantee the outbox relay relies on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from db.models.resiliant import ScheduledJobTable
from foundation import BaseService
from foundation.resiliant.schedule import ScheduleConfig, ScheduleJobStatus
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ._recurrence import utcnow_naive


class ScheduleRepository(BaseService):
    """Repository for scheduled-job database operations."""

    def __init__(self, config: ScheduleConfig) -> None:
        super().__init__()
        self.config = config

    async def save(
        self, session: AsyncSession, job: ScheduledJobTable
    ) -> ScheduledJobTable:
        """Persist a new job and flush to obtain its generated id."""
        session.add(job)
        await session.flush()
        return job

    async def get(
        self, session: AsyncSession, job_id: str
    ) -> Optional[ScheduledJobTable]:
        """Return a single job by primary key (or ``None``)."""
        result = await session.execute(
            select(ScheduledJobTable).where(ScheduledJobTable.id == job_id)
        )
        return result.scalar_one_or_none()

    async def fetch_due_batch(
        self,
        session: AsyncSession,
        batch_size: Optional[int] = None,
    ) -> List[ScheduledJobTable]:
        """Claim a batch of due jobs and transition them to ``RUNNING``.

        A job is due when it is ``SCHEDULED`` and ``next_run_at <= now``. The
        batch is locked with ``FOR UPDATE SKIP LOCKED`` (when enabled) so
        concurrent workers never claim the same row.
        """
        batch_size = batch_size or self.config.batch_size
        now = utcnow_naive()

        query = (
            select(ScheduledJobTable)
            .where(
                and_(
                    ScheduledJobTable.status == ScheduleJobStatus.SCHEDULED,
                    ScheduledJobTable.next_run_at <= now,
                )
            )
            .order_by(ScheduledJobTable.next_run_at.asc())
            .limit(batch_size)
        )
        if self.config.use_skip_locked:
            query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        jobs = list(result.scalars().all())

        if jobs:
            ids = [j.id for j in jobs]
            await session.execute(
                update(ScheduledJobTable)
                .where(ScheduledJobTable.id.in_(ids))
                .values(status=ScheduleJobStatus.RUNNING, claimed_at=now)
            )
            await session.commit()

        return jobs

    async def mark_succeeded(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        next_run_at: Optional[datetime],
    ) -> None:
        """Record a successful fire.

        ``next_run_at is None`` (a ONCE job, or a recurring job that hit
        ``max_runs``) → terminal ``DONE``. Otherwise the job returns to
        ``SCHEDULED`` with its next occurrence and a reset attempt counter.
        """
        now = utcnow_naive()
        job = await self.get(session, job_id)
        if job is None:
            self.logger.warning('Scheduled job %s not found for mark_succeeded', job_id)
            return

        run_count = job.run_count + 1
        reached_cap = job.max_runs is not None and run_count >= job.max_runs

        if next_run_at is None or reached_cap:
            new_status = ScheduleJobStatus.DONE
            new_next_run = job.next_run_at  # unchanged; terminal
        else:
            new_status = ScheduleJobStatus.SCHEDULED
            new_next_run = next_run_at

        await session.execute(
            update(ScheduledJobTable)
            .where(ScheduledJobTable.id == job_id)
            .values(
                status=new_status,
                next_run_at=new_next_run,
                last_run_at=now,
                claimed_at=None,
                run_count=run_count,
                attempts=0,
                last_error=None,
            )
        )
        await session.commit()

    async def mark_failed(
        self,
        session: AsyncSession,
        job_id: str,
        error: str,
        *,
        next_run_at: Optional[datetime] = None,
    ) -> None:
        """Record a failed fire.

        Increments ``attempts``. While the retry budget remains, the job is
        re-scheduled after ``retry_backoff_seconds`` (or an explicit
        ``next_run_at``). Once exhausted it moves to terminal ``FAILED``.
        """
        now = utcnow_naive()
        job = await self.get(session, job_id)
        if job is None:
            self.logger.warning('Scheduled job %s not found for mark_failed', job_id)
            return

        attempts = job.attempts + 1
        exhausted = attempts >= job.max_retries

        if exhausted:
            new_status = ScheduleJobStatus.FAILED
            new_next_run = job.next_run_at
            self.logger.error(
                'Scheduled job %s (%s) FAILED after %s attempts: %s',
                job_id,
                job.job_name,
                attempts,
                error,
            )
        else:
            new_status = ScheduleJobStatus.SCHEDULED
            new_next_run = next_run_at or (
                now + timedelta(seconds=self.config.retry_backoff_seconds)
            )
            self.logger.warning(
                'Scheduled job %s (%s) failed (attempt %s/%s), retrying at %s: %s',
                job_id,
                job.job_name,
                attempts,
                job.max_retries,
                new_next_run,
                error,
            )

        await session.execute(
            update(ScheduledJobTable)
            .where(ScheduledJobTable.id == job_id)
            .values(
                status=new_status,
                next_run_at=new_next_run,
                claimed_at=None,
                attempts=attempts,
                last_error=error[:1000],
            )
        )
        await session.commit()

    async def cancel(self, session: AsyncSession, job_id: str) -> None:
        """Cancel a job (idempotent; only affects non-terminal rows)."""
        await session.execute(
            update(ScheduledJobTable)
            .where(
                and_(
                    ScheduledJobTable.id == job_id,
                    ScheduledJobTable.status.in_(
                        [ScheduleJobStatus.SCHEDULED, ScheduleJobStatus.RUNNING]
                    ),
                )
            )
            .values(status=ScheduleJobStatus.CANCELLED, claimed_at=None)
        )
        await session.commit()

    async def reset_stale_running(
        self,
        session: AsyncSession,
        timeout_seconds: Optional[int] = None,
    ) -> int:
        """Return jobs stuck in ``RUNNING`` (crashed worker) to ``SCHEDULED``."""
        timeout_seconds = timeout_seconds or self.config.claim_timeout_seconds
        threshold = utcnow_naive() - timedelta(seconds=timeout_seconds)

        result = await session.execute(
            update(ScheduledJobTable)
            .where(
                and_(
                    ScheduledJobTable.status == ScheduleJobStatus.RUNNING,
                    ScheduledJobTable.claimed_at < threshold,
                )
            )
            .values(status=ScheduleJobStatus.SCHEDULED, claimed_at=None)
        )
        count = result.rowcount
        await session.commit()
        if count:
            self.logger.warning('Reset %s stale RUNNING scheduled jobs', count)
        return count

    async def get_stats(self, session: AsyncSession) -> dict:
        """Return per-status counters plus the oldest overdue job age."""
        result = await session.execute(
            select(
                ScheduledJobTable.status,
                func.count(ScheduledJobTable.id).label('count'),
            ).group_by(ScheduledJobTable.status)
        )
        counts = {row.status: row.count for row in result}

        result = await session.execute(
            select(func.min(ScheduledJobTable.next_run_at)).where(
                ScheduledJobTable.status == ScheduleJobStatus.SCHEDULED
            )
        )
        oldest_due = result.scalar_one_or_none()
        now = utcnow_naive()

        stats = {status.value: counts.get(status, 0) for status in ScheduleJobStatus}
        stats['oldest_overdue_seconds'] = (
            (now - oldest_due).total_seconds()
            if oldest_due is not None and oldest_due < now
            else 0.0
        )
        return stats
