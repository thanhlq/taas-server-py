from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from ..base import SoftDeleteColumns
from .constants import TAG_TABLE, PROJECT_WIKI_TABLE


class ProjectWiki(UUIDv7Base, SoftDeleteColumns):
    __tablename__ = PROJECT_WIKI_TABLE

    title: Mapped[str] = mapped_column(index=True)
    content: Mapped[str]
    published: Mapped[bool] = mapped_column(default=False)
    tags: Mapped[list["BlogTag"]] = relationship(
        secondary=blog_post_tag,
        back_populates="posts",
        lazy="selectin",
    )
