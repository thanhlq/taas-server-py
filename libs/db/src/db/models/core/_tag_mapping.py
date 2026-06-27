from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import TAG_MAPPING_TABLE, TAG_TABLE


class TagMapping(UUIDv7Base, SoftDeleteColumns):
    """Tag Mapping (PPM domain)."""

    __tablename__ = TAG_MAPPING_TABLE

    tag_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TAG_TABLE}.id'), nullable=True
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(length=50), index=True, nullable=True, default=None
    )
    entity_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
    assigned_by: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
