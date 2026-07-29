from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from foundation.iam.types import TeamRoles
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import ORGANIZATION_MEMBER_TABLE, ORGANIZATION_TABLE, TEAM_MEMBER_TABLE, TEAM_TABLE, USER_ACCOUNT_TABLE

if TYPE_CHECKING:
    from ._team import Team
    from ._organization import Organization
    from ._user import User


class OrganizationMember(UUIDv7AuditBase):
    """Team Membership."""

    __tablename__ = ORGANIZATION_MEMBER_TABLE
    __table_args__ = (UniqueConstraint('user_id', 'organization_id'),)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f'{USER_ACCOUNT_TABLE}.id', ondelete='cascade'), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False
    )
    role: Mapped[TeamRoles] = mapped_column(
        String(length=50),
        default=TeamRoles.MEMBER,
        nullable=False,
        index=True,
    )
    is_owner: Mapped[bool] = mapped_column(default=False, nullable=False)

    user: Mapped[User] = relationship(
        back_populates='organizations',
        foreign_keys='OrganizationMember.user_id',
        innerjoin=True,
        uselist=False,
        lazy='joined',
    )
    name: AssociationProxy[str] = association_proxy('user', 'name')
    email: AssociationProxy[str] = association_proxy('user', 'email')
    organization: Mapped[Organization] = relationship(
        back_populates='members',
        foreign_keys='OrganizationMember.organization_id',
        innerjoin=True,
        uselist=False,
        lazy='joined',
    )
    organization_name: AssociationProxy[str] = association_proxy('organization', 'name')
