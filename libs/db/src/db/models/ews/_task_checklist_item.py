from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE
from .constants import TASK_CHECKLIST_ITEMS_TABLE, TASKS_TABLE


class TaskChecklistItem(UUIDv7AuditBase):
    """Task Checklist Item.

    The items that are part of a checklist associated with a task.
    Each task is linked to multiple checklist items that can be marked as
    completed.
    """

    __tablename__ = TASK_CHECKLIST_ITEMS_TABLE

    task_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    is_completed: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    completed_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text("'-1'::integer")
    )
