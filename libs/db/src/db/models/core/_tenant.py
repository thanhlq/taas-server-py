from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.mixins import AuditColumns
from advanced_alchemy.types import GUID, DateTimeUTC
from foundation.iam.types import TenantAccountType, TenantStatus
from foundation.utils.id import generate_db_id
from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import (
    ID_COLUMN_TYPE,
    JSONB,
    TENANT_ID_COLUMN_TYPE,
    ArchivedColumns,
    BaseDBModel,
    SlugKey,
    SoftDeleteColumns,
)
from .constants import TENANT_TABLE


class Tenant(BaseDBModel, SoftDeleteColumns, SlugKey, AuditColumns, ArchivedColumns):
    """Tenant model representing a Keycloak realm"""

    __tablename__ = TENANT_TABLE
    __table_args__ = (
        UniqueConstraint('id', 'slug'),
        Index('ux_taas_tenants_slug', 'slug', unique=True),
        Index('ux_taas_tenants_tenant_code', 'tenant_code', unique=True),
        # Iam-0100: exactly one root tenant (the platform owner).
        Index('ux_taas_tenants_is_root', 'is_root', unique=True, postgresql_where=text('is_root')),
        CheckConstraint("account_type in ('organization', 'personal')", name='ck_taas_tenants_account_type'),
    )

    id: Mapped[TENANT_ID_COLUMN_TYPE] = mapped_column(
        GUID(length=16), primary_key=True, default=generate_db_id
    )
    # Human / billing code (8 digits), never the primary key.
    tenant_code: Mapped[str] = mapped_column(TEXT, nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TenantAccountType.ORGANIZATION.value
    )
    is_root: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text('false')
    )
    # Platform-managed flags, e.g. sub_organizations_enabled (Iam-0140, set by the billing plan).
    sys_settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    onboarded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    # Id that stored in Keycloak i.e. organization_id in Keycloak
    directory_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=False
    )
    realm_name: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, index=False
    )

    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    commercial_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    alias_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

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

    # Status and flags
    is_individual: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    # status = Column(
    #     String(20), nullable=False, default=TenantStatus.ACTIVE, index=True
    # )
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus), nullable=False, default=TenantStatus.ACTIVE, index=True
    )
    root_account_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        nullable=True,
        index=True,
    )

    # JSONB fields
    analytics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tenant_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Avatar and styling
    avatar_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Relationships
    # users: Mapped[Set['UserTable']] = relationship(
    #     back_populates='tenant',
    #     collection_class=set,
    # )
