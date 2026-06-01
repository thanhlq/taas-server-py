from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import SlugKey
from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    Boolean,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import ID_COLUMN_TYPE, JSONB
from db.models.ews.constants import CRM_ACCOUNTS_TABLE
from db.models.ews._crm_account_address import CrmAccountAddress


class CrmAccount(UUIDv7AuditBase, SlugKey):
    """Account (Client/Customer)"""

    __tablename__ = CRM_ACCOUNTS_TABLE

    org_id: Mapped[Optional[str]] = mapped_column(
        TEXT,
        # ForeignKey(f'{ORGANIZATIONS_TABLE}.{ID_COLUMN_NAME}'),
        nullable=True,
        index=True,
    )

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    commercial_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    alias_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    account_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    # Relationships
    parent_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        TEXT, nullable=True, index=True
    )
    user_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        TEXT, nullable=True, index=True
    )
    # group_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
    #     TEXT, nullable=True
    # )

    # Privacy
    privacy: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    # Contact information
    email: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    email_alt1: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_alt2: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    email_alt3: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_office: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_alternate: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    phone_sanitized: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Business information
    ownership: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    sic_code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    commercial_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    account_function: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    employees: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    industry_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    annual_revenue: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    account_rank: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Status and flags
    status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'active'"), index=True
    )
    is_individual: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false'), index=True
    )
    starred: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false'), index=True
    )
    starred_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    # Financial
    invoice_warn: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    invoice_warn_message: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    sale_warn: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    sale_warn_message: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    debit_limit: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 6), nullable=True
    )
    currency_id: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'USD'")
    )

    # Campaign
    campaign_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # Styling
    avatar_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    # JSONB fields
    analytics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    account_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    last_time_entries_checked: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )

    # addresses:
    addresses: Mapped[list[CrmAccountAddress]] = relationship(
        back_populates='user',
        lazy='noload',
        cascade='all, delete',
        uselist=True,
    )

    # Relationships
    # projects: Mapped[List['ProjectOrm']] = relationship(
    #     back_populates='client', foreign_keys='ProjectOrm.client_id'
    # )
