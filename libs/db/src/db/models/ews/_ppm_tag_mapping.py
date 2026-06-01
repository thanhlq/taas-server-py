from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from ..types import TAGS_MAPPING_TABLE, TAGS_TABLE


class PpmTagMapping(UUIDv7Base, SoftDeleteColumns):
    """Tag Mapping (PPM domain)."""

    __tablename__ = TAGS_MAPPING_TABLE

    tag_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TAGS_TABLE}.id'), nullable=True
    )
    object_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    object_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
