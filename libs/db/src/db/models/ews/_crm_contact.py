"""CRM contact (taas-specs/crm/contacts/contacts-spec.md, ADR-8): a person we talk to, usually at an account. E-mails
and phones are lists (one primary, mirrored in ``email`` / ``phone`` for search and the duplicate guard), addresses a
list (primary · other); soft delete."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import TEXT, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import CRM_ACCOUNTS_TABLE, CRM_CONTACTS_TABLE

PHONE_KINDS = ('office', 'mobile', 'home', 'other')
ADDRESS_KINDS = ('primary', 'other')


class CrmContact(UUIDv7AuditBase):
    """A person at an account (or on its own)."""

    __tablename__ = CRM_CONTACTS_TABLE
    __table_args__ = (
        Index('ix_taas_crm_contacts_scope', 'organization_id', 'deleted_at'),
        Index('ix_taas_crm_contacts_email', 'organization_id', 'email'),
        Index('ix_taas_crm_contacts_name', 'organization_id', 'name'),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{CRM_ACCOUNTS_TABLE}.id', ondelete='set null'),
        nullable=True,
        index=True,
    )
    """The contact's company (ADR-8); null = a contact on its own."""
    salutation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(320), nullable=False)
    """"First Last" (else the primary e-mail): list sort and search."""
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    """Primary e-mail (lower case)."""
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """Primary phone."""
    emails: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    """``[{value, primary, opt_out, invalid}]``."""
    phones: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    """``[{value, kind, primary}]`` (kind: ``PHONE_KINDS``)."""
    addresses: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    """``[{kind, street, postal_code, city, state, country}]`` (kind: ``ADDRESS_KINDS``)."""
    owner: Mapped[str | None] = mapped_column(String(320), nullable=True)
    """User ref (e-mail) who owns the relationship (*Assigned to*)."""
    lead_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reports_to_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{CRM_CONTACTS_TABLE}.id', ondelete='set null'),
        nullable=True,
    )
    labels: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
