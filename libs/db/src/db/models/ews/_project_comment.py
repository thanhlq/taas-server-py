from __future__ import annotations

from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index

from ..base import SoftDeleteColumns
from .constants import PROJECTS_COMMENTS_TABLE


class ProjectComment(UUIDv7Base, SoftDeleteColumns):
    """Project Comments"""

    __tablename__ = PROJECTS_COMMENTS_TABLE
    __table_args__ = (
        Index(
            f'{PROJECTS_COMMENTS_TABLE}_default_btree_index',
            'project_id',
            'object_id',
            'object_type',
        ),
    )

    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    comment_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    """Original comment text"""
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'::character")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    object_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    object_type: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        server_default=text("'project'::character"),
        index=True,
    )
    privacy: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'object'::character")
    )
