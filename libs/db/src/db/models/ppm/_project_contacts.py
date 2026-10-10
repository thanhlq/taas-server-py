"""Contacts of a project (taas-specs/ppm/project/project-create-client-contacts.md, Ppm-0115): CRM contacts linked to
the project, one of them the default (the client's main contact for this project)."""

from __future__ import annotations

from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import TENANT_TABLE
from db.models.ews.constants import CRM_CONTACTS_TABLE, PROJECTS_TABLE

from .constants import PPM_PROJECT_CONTACTS_TABLE


class PpmProjectContact(UUIDv7AuditBase):
    __tablename__ = PPM_PROJECT_CONTACTS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_project_contacts_pair', 'project_id', 'contact_id', unique=True
        ),
        Index(
            'ux_taas_ppm_project_contacts_default',
            'project_id',
            unique=True,
            postgresql_where=text('is_default'),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    contact_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{CRM_CONTACTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
