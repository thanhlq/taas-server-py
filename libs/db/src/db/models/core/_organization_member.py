from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from foundation.iam.types import MembershipJoinedVia, OrganizationRoles
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constants import ORGANIZATION_MEMBER_TABLE, ORGANIZATION_TABLE, TENANT_TABLE, USER_ACCOUNT_TABLE

if TYPE_CHECKING:
    from ._organization import Organization
    from ._user import User


class OrganizationMember(UUIDv7AuditBase):
    """Organization membership with its coarse role; a user may join several organizations (Iam-0160).

    Fine-grained rights are casbin grants (`taas_casbin_rule`, domain ``org:<organization_id>``).
    """

    __tablename__ = ORGANIZATION_MEMBER_TABLE
    __table_args__ = (
        UniqueConstraint('user_id', 'organization_id'),
        Index('ix_taas_organization_members_tenant_user', 'tenant_id', 'user_id'),
        CheckConstraint(
            "role in ('tenant_admin', 'org_admin', 'org_member')", name='ck_taas_organization_members_role'
        ),
        CheckConstraint(
            "joined_via in ('registration', 'admin', 'join_link', 'sso')",
            name='ck_taas_organization_members_joined_via',
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f'{USER_ACCOUNT_TABLE}.id', ondelete='cascade'), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(length=50),
        default=OrganizationRoles.ORG_MEMBER.value,
        nullable=False,
        index=True,
    )
    is_owner: Mapped[bool] = mapped_column(default=False, nullable=False)
    joined_via: Mapped[str] = mapped_column(
        String(length=20), default=MembershipJoinedVia.REGISTRATION.value, nullable=False
    )
    invitation_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True, default=None)

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
