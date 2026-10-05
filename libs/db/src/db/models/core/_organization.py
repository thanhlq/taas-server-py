"""
- An organization represents a company or entity that can have multiple teams, projects, and users.
It serves as the top-level container for all resources and permissions within the system.

- In a more simple system, an organization might just be a workspace or account.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import SlugKey
from advanced_alchemy.types import GUID
from foundation.iam.types import OrganizationStatus
from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import JSONB, TENANT_ID_COLUMN_TYPE, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

if TYPE_CHECKING:
    from ._organization_member import OrganizationMember


class Organization(UUIDv7AuditBase, SlugKey, SoftDeleteColumns):
    """Organization: the tree of a tenant. Root (parent_id NULL) = the tenant itself (Iam-0120)."""

    __tablename__ = ORGANIZATION_TABLE
    __table_args__ = (
        # SlugKey's own constraints (overridden by this __table_args__).
        UniqueConstraint('slug', name='uq_taas_organizations_slug'),
        Index('ix_taas_organizations_slug_unique', 'slug', unique=True),
        Index('ux_taas_organizations_root', 'tenant_id', unique=True, postgresql_where=text('parent_id IS NULL')),
        Index('ix_taas_organizations_path', 'path', postgresql_ops={'path': 'text_pattern_ops'}),
        CheckConstraint('depth BETWEEN 0 AND 5', name='ck_taas_organizations_depth'),
        CheckConstraint('(parent_id IS NULL) = (depth = 0)', name='ck_taas_organizations_root_depth'),
    )

    tenant_id: Mapped[TENANT_ID_COLUMN_TYPE] = mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=True
    )
    # Materialized path of ids, '/<root>/<child>/': subtree = path LIKE '<path>%'.
    path: Mapped[str] = mapped_column(TEXT, nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text('0'))
    # Keycloak group / organization id when the provider mirrors it.
    directory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    commercial_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    alias_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    org_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Address information
    address_street: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    address_city: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    address_state: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    address_postal_code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    address_country_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Billing address
    # Billing to tenant only

    # Contact information
    email: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_alt1: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_alt2: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_alt3: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_office: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_alternate: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Business information
    ownership: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    sic_code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    commercial_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    account_function: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    employees: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    industry_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    annual_revenue: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_sanitized: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    account_rank: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    invoice_warn: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    invoice_warn_message: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    last_time_entries_checked: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    sale_warn: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    sale_warn_message: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    debit_limit: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    is_individual: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    # status = Column(
    #     String(20), nullable=False, default=OrganizationStatus.ACTIVE, index=True
    # )
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus),
        nullable=False,
        default=OrganizationStatus.ACTIVE,
        index=True,
    )

    # Avatar and styling
    avatar_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # JSONB fields
    analytics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    org_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    # projects: Mapped[List['ProjectOrm']] = relationship(
    #     back_populates='organization', foreign_keys='ProjectOrm.org_id'
    # )

    members: Mapped[list[OrganizationMember]] = relationship(
        back_populates='organization',
        cascade='all, delete',
        passive_deletes=True,
        lazy='selectin',
    )
