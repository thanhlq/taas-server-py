from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import PROJECTS_TABLE, PROJECTS_UPDATES_TABLE


class ProjectUpdate(UUIDv7Base, SoftDeleteColumns):
    """Project Updates"""

    __tablename__ = PROJECTS_UPDATES_TABLE

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'::character")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    attachments: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_cc: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
