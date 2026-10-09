"""PPM time tracking (taas-specs/ppm/time-expense/time-tracking-spec.md §3.3): weekly timesheets (one person × one week,
submitted and approved per project section through the generic approvals) and time categories (``project`` work,
``internal`` time without a project). Entries stay in ``taas_timelogs`` (``db.models.ews.Timelog``)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import PPM_TIME_CATEGORIES_TABLE, PPM_TIMESHEETS_TABLE

TIMESHEET_STATUSES = (
    'open',
    'submitted',
    'partially_approved',
    'approved',
    'rejected',
    'reopened',
)
CATEGORY_KINDS = ('project', 'internal')


class PpmTimeCategory(UUIDv7AuditBase):
    """What time is spent on: ``project`` work (default) or ``internal`` (admin, training, pre-sales) without a project."""

    __tablename__ = PPM_TIME_CATEGORIES_TABLE
    __table_args__ = (
        CheckConstraint("kind in ('project', 'internal')", name='kind'),
        Index('ux_taas_ppm_time_categories_key', 'organization_id', 'key', unique=True),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'internal'")
    )
    billable_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('true')
    )
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )


class PpmTimesheet(UUIDv7AuditBase):
    """One person × one week (organization week start); created on first need."""

    __tablename__ = PPM_TIMESHEETS_TABLE
    __table_args__ = (
        CheckConstraint(
            "status in ('open', 'submitted', 'partially_approved', 'approved', 'rejected', 'reopened')",
            name='status',
        ),
        Index(
            'ux_taas_ppm_timesheets_week',
            'organization_id',
            'user_id',
            'period_start',
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(320), nullable=False)
    """The person (e-mail or id, like ``taas_timelogs.user_id``)."""
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'open'")
    )
    total_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    billable_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
