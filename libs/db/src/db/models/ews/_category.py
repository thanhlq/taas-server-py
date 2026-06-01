from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import CATEGORY_TABLE


class Category(UUIDv7Base, SoftDeleteColumns):
    """Project Category - for grouping and filtering projects (e.g. product A, product B)."""

    __tablename__ = CATEGORY_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'::character")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    object_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    object_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    parent_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{CATEGORY_TABLE}.id'), nullable=True
    )
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    last_used_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    parent_category: Mapped[Optional['Category']] = relationship(
        remote_side='Category.id', foreign_keys=[parent_id]
    )
