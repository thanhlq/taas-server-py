from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import SlugKey, UniqueMixin
from advanced_alchemy.utils.text import slugify
from platform_core.models.common import ObjectScope, ObjectStatus
from sqlalchemy import (
    ColumnElement,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import ID_COLUMN_TYPE

from .constants import TAG_TABLE

if TYPE_CHECKING:
    from collections.abc import Hashable

    from ._team import Team


class Tag(UUIDv7AuditBase, SlugKey, UniqueMixin):
    """Tag.

    Enique (teannt, slug) or (org, slug) or (project, slug) or (parent, slug).
    """

    __tablename__ = TAG_TABLE
    name: Mapped[str] = mapped_column(String(length=100), index=True, nullable=False)
    color: Mapped[str | None] = mapped_column(
        String(length=30), index=False, nullable=True
    )
    description: Mapped[str | None] = mapped_column(
        String(length=255), index=False, nullable=True
    )
    icon: Mapped[str | None] = mapped_column(
        String(length=100), index=False, nullable=True
    )

    status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=ObjectStatus.ACTIVE.value,
        index=True,
    )
    scope: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=ObjectScope.TENANT.value,
        index=True,
    )

    tenant_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
    org_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
    project_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
    parent_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )

    teams: Mapped[list[Team]] = relationship(
        secondary=lambda: _team_tag(),
        back_populates='tags',
        viewonly=True,
        lazy='noload',
    )

    @classmethod
    def unique_hash(cls, name: str, slug: str | None = None) -> Hashable:
        return slugify(name)

    @classmethod
    def unique_filter(
        cls,
        name: str,
        slug: str | None = None,
    ) -> ColumnElement[bool]:
        return cls.slug == slugify(name)


def _team_tag() -> Table:
    from ._team_tag import team_tag

    return team_tag
