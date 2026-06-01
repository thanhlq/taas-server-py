from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import PROJECTS_TABLE, TASKS_TABLE, TIMELOG_TABLE

if TYPE_CHECKING:
    from ._project import Project
    from ._task import Task


class Timelog(UUIDv7Base, SoftDeleteColumns):
    """Timelog"""

    __tablename__ = TIMELOG_TABLE

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
    location_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    # Format: longitude,latitude, altitude, accuracy
    location: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    project: Mapped[Optional['Project']] = relationship(
        back_populates='timelogs', foreign_keys=[project_id]
    )
    task: Mapped[Optional['Task']] = relationship(
        back_populates='timelogs', foreign_keys=[task_id]
    )
