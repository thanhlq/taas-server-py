from __future__ import annotations

from datetime import datetime
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID, DateTimeUTC
from foundation.iam.types import OrganizationRoles
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .constants import ORGANIZATION_INVITATION_TABLE, ORGANIZATION_TABLE, TENANT_TABLE, USER_ACCOUNT_TABLE


class OrganizationInvitation(UUIDv7AuditBase):
    """Join link of an organization (Iam-0160): single- or multi-use, only the token hash is stored."""

    __tablename__ = ORGANIZATION_INVITATION_TABLE
    __table_args__ = (
        Index('ux_taas_organization_invitations_token_hash', 'token_hash', unique=True),
        Index('ix_taas_organization_invitations_org', 'organization_id'),
        CheckConstraint("role in ('org_admin', 'org_member')", name='ck_taas_organization_invitations_role'),
        CheckConstraint(
            'max_uses >= 1 AND used_count >= 0 AND used_count <= max_uses',
            name='ck_taas_organization_invitations_uses',
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False
    )
    # sha256 (hex) of the link token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL = open link (anyone with the link)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=OrganizationRoles.ORG_MEMBER.value)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text('1'))
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text('0'))
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{USER_ACCOUNT_TABLE}.id', ondelete='set null'), nullable=True
    )
