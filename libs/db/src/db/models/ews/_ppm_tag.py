from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ..base import SoftDeleteColumns
from .constants import TAG_TABLE


class PpmTag(UUIDv7Base, SoftDeleteColumns):
    """Tag (PPM domain — generic object tagging)."""

    __tablename__ = TAG_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    object_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    object_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    last_used_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
