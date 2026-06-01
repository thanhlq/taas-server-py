from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from ..types import TASKS_TABLE, TASKS_USERS_TABLE


class TaskUser(UUIDv7Base, SoftDeleteColumns):
    """Task-User relationship"""

    __tablename__ = TASKS_USERS_TABLE

    organization_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    task_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
