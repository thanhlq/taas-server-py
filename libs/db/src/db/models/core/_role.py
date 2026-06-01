from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import SlugKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import ROLE_TABLE

if TYPE_CHECKING:
    from ._user_role import UserRole


class Role(UUIDv7AuditBase, SlugKey):
    """Role."""

    __tablename__ = ROLE_TABLE

    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    users: Mapped[list[UserRole]] = relationship(
        back_populates='role',
        cascade='all, delete',
        lazy='noload',
        viewonly=True,
    )
