from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from advanced_alchemy.types import GUID
from sqlalchemy import TEXT, TIMESTAMP, Boolean, Date, ForeignKey, Index, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import PROJECTS_TABLE, TASKS_TABLE, TIMELOG_TABLE

if TYPE_CHECKING:
    from ._project import Project
    from ._task import Task


class Timelog(UUIDv7Base, SoftDeleteColumns):
    """Timelog"""

    __tablename__ = TIMELOG_TABLE
    __table_args__ = (
        Index('ix_taas_timelogs_user_date', 'user_id', 'entry_date'),
        Index('ix_taas_timelogs_project_date', 'project_id', 'entry_date'),
        Index(
            'ux_taas_timelogs_running',
            'user_id',
            unique=True,
            postgresql_where=text('is_recording and deleted_at is null'),
        ),
    )

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    task_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    log_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )
    log_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    period_from: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    period_to: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    timelog_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'Regular'")
    )
    is_billable: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    is_billed: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    pay_status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'NA'")
    )
    invoice_number: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    billing_invoice_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'Draft'")
    )
    approved_user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    approved_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    approved_notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    is_recording: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Time tracking V2 (taas-specs/ppm/time-expense/time-tracking-spec.md §3.1)
    tenant_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    organization_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    """Calendar day of the entry (the person's day); ``log_date`` is kept for older readers."""
    time_category_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    source: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    """``manual`` · ``timer`` · ``timesheet`` · ``import`` · ``mobile``."""
    timesheet_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    reverses_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    correction_reason: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    needs_review: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    """Timer stopped by the auto-stop limit (Ppm-1212)."""
    created_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    location_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    # Format: longitude,latitude, altitude, accuracy
    location: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    project: Mapped[Optional['Project']] = relationship(
        back_populates='timelogs', foreign_keys=[project_id]
    )
    task: Mapped[Optional['Task']] = relationship(
        back_populates='timelogs', foreign_keys=[task_id]
    )
