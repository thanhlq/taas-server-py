from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Float, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import PROJECTS_ITERATIONS_TABLE, PROJECTS_TABLE


class ProjectIteration(UUIDv7Base, SoftDeleteColumns):
    """Iteration (sprint) of a project: a time box tasks are planned into."""

    __tablename__ = PROJECTS_ITERATIONS_TABLE

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    goal: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # planned | active | completed
    status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'planned'")
    )
    start_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    display_order: Mapped[Optional[float]] = mapped_column(
        Float(precision=6), nullable=True, server_default=text('-1')
    )
