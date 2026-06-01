from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from ..types import PROJECTS_ACTIONS_TABLE, PROJECTS_TABLE


class ProjectAction(UUIDv7Base, SoftDeleteColumns):
    """Project Actions"""

    __tablename__ = PROJECTS_ACTIONS_TABLE

    organization_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    action_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    action_color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    action_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    action_value: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )
