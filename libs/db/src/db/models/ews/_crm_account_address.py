from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import SlugKey
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import ID_COLUMN_TYPE
from db.models.ews.constants import CRM_ACCOUNTS_ADDRESSES_TABLE, CRM_ACCOUNTS_TABLE

if TYPE_CHECKING:
    from db.models import CrmAccount


class CrmAccountAddress(UUIDv7AuditBase, SlugKey):
    """Account (Client/Customer) Address"""

    __tablename__ = CRM_ACCOUNTS_ADDRESSES_TABLE

    # Address information
    address_street: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_postal_code: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    address_country_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_country_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # address_type can be 'billing', 'shipping', 'office', etc.
    address_type: Mapped[Optional[str]] = mapped_column(
        String(30), index=True, default='office', nullable=False
    )

    account_id: Mapped[ID_COLUMN_TYPE] = mapped_column(
        ForeignKey(f'{CRM_ACCOUNTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )

    # Relationships
    account: Mapped[CrmAccount] = relationship(
        back_populates='addresses',
        lazy='noload',
        cascade='all, delete',
        uselist=False,
    )

    # Billing address
    # is_same_address: Mapped[bool] = mapped_column(default=True)
    # billing_street: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # billing_city: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # billing_state: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # billing_postal_code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # billing_country_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    # billing_country_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
