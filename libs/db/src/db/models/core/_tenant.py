from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import TEXT, TIMESTAMP, Boolean, Enum, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from db.models.ews.constants import TENANT_TABLE
from db.models.core.enums import TenantStatus


class TenantTable(SoftDeleteColumns):
    """Tenant model representing a Keycloak realm"""

    __tablename__ = TENANT_TABLE

    # id: Mapped[str] = mapped_column(
    #     Text,
    #     server_default=text('gen_random_uuid()'),
    #     primary_key=True,
    # )
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
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
    is_active: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    is_individual: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    # status = Column(
    #     String(20), nullable=False, default=TenantStatus.ACTIVE, index=True
    # )
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus), nullable=False, default=TenantStatus.ACTIVE, index=True
    )
    root_account_id: Mapped[ID_COLUMN_TYPE] = mapped_column(
        nullable=False,
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
