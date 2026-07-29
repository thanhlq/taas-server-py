"""
Scheduled-job database model (durable timers / schedules / cron).

Backs :mod:`foundation.resiliant.schedule`. A row is a persisted "wake at"
timestamp: the :class:`resiliant.schedule.SchedulerPoller` claims due rows with
``FOR UPDATE SKIP LOCKED`` and fires them. Because the wake-up time lives in the
database, the timer survives any number of worker restarts in between.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from advanced_alchemy.base import UUIDv7AuditBase
from foundation.resiliant.schedule import ScheduleJobKind, ScheduleJobStatus
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Column,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.config import RESILIANT_TABLE_PREFIX


class ScheduledJobTable(UUIDv7AuditBase):
    """A durable timer / recurring schedule.

    Indexes:
        - idx_schedule_due: the hot path for the poller — claim ``SCHEDULED``
          rows whose ``next_run_at`` has arrived, oldest first.
        - idx_schedule_job_name: query/inspect a named job.
    """

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}scheduled_jobs'

    # Identity / recurrence
    job_name = Column(String(255), nullable=False, index=True)
    """Logical name — maps to a registered dispatch callback or a channel."""

    kind = Column(
        Enum(ScheduleJobKind), nullable=False, default=ScheduleJobKind.ONCE
    )
    cron_expr = Column(String(255), nullable=True)
    """Cron expression when ``kind == CRON`` (e.g. ``'0 2 * * *'``)."""
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Recurrence period when ``kind == INTERVAL``."""

    # Dispatch target — publish to ``channel`` when set, else invoke the
    # callback registered under ``job_name``.
    channel = Column(String(255), nullable=True)
    event_type = Column(String(255), nullable=True)
    ordering_key = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=True)
    headers = Column(JSON, nullable=True, default=dict)

    # Timers (naive UTC to match the rest of the resiliant tables)
    next_run_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False), nullable=False, index=True
    )
    """The durable wake-up time. The poller fires the job once this passes."""
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True
    )
    """When a poller claimed the row (RUNNING); used for stale recovery."""

    # Status / bookkeeping
    status = Column(
        Enum(ScheduleJobStatus),
        nullable=False,
        default=ScheduleJobStatus.SCHEDULED,
        index=True,
    )
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Cap on total fires for a recurring job (``None`` = unlimited)."""

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Consecutive failed attempts of the *current* occurrence."""
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error = Column(Text, nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-safe dictionary."""
        return {
            'id': self.id,
            'job_name': self.job_name,
            'kind': self.kind.value if self.kind else None,
            'cron_expr': self.cron_expr,
            'interval_seconds': self.interval_seconds,
            'channel': self.channel,
            'event_type': self.event_type,
            'ordering_key': self.ordering_key,
            'payload': self.payload,
            'headers': self.headers,
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'status': self.status.value if self.status else None,
            'run_count': self.run_count,
            'max_runs': self.max_runs,
            'attempts': self.attempts,
            'max_retries': self.max_retries,
            'last_error': self.last_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f'<ScheduledJob(id={self.id}, job_name={self.job_name}, '
            f'kind={self.kind}, status={self.status}, next_run_at={self.next_run_at})>'
        )


# The poller's claim query: SCHEDULED rows ordered by due time.
Index(
    'idx_schedule_due',
    ScheduledJobTable.status,
    ScheduledJobTable.next_run_at,
)
