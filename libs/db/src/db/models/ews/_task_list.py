from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, Float, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import PROJECTS_TABLE, TASKS_LISTS_TABLE


class TaskList(UUIDv7Base, SoftDeleteColumns):
    """Task list — a named group of a project's tasks (category for management and automation)."""

    __tablename__ = TASKS_LISTS_TABLE

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_order: Mapped[Optional[float]] = mapped_column(
        Float(precision=6), nullable=True, server_default=text('-1')
    )
