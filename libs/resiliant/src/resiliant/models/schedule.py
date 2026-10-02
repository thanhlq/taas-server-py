"""
Scheduled jobs (same table as ``@taas/resiliant``): one-off, interval and cron jobs.

Statuses (``ScheduleJobStatus``): ``scheduled`` → ``running`` (lease, ``claimed_at``) →
``scheduled`` (recurring) | ``done`` | ``failed``; ``cancelled``. ``unique_key`` makes a
job a singleton while it is scheduled or running.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from foundation.resiliant.schedule import ScheduleJobKind, ScheduleJobStatus
from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from resiliant.models.base import (
    EnumText,
    Jsonb,
    ResiliantBase,
    Timestamptz,
    bigint_identity_pk,
    created_at_column,
    updated_at_column,
)
from resiliant.models.config import RESILIANT_TABLE_PREFIX


class ScheduledJobTable(ResiliantBase):
    __tablename__ = f'{RESILIANT_TABLE_PREFIX}scheduled_jobs'

    id: Mapped[int] = bigint_identity_pk()
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    unique_key: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[ScheduleJobKind] = mapped_column(
        EnumText(ScheduleJobKind), nullable=False
    )
    cron_expr: Mapped[str | None] = mapped_column(Text)
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(Text)
    ordering_key: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(Jsonb, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(Jsonb)
    next_run_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    claimed_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    status: Mapped[ScheduleJobStatus] = mapped_column(
        EnumText(ScheduleJobStatus),
        nullable=False,
        default=ScheduleJobStatus.SCHEDULED,
        server_default=text("'scheduled'"),
    )
    run_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text('0')
    )
    max_runs: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text('0')
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text('3')
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


__all__ = ['ScheduledJobTable']
