"""PPM intake (taas-specs/ppm/intake/intake-spec.md §3): request forms (draft + immutable published versions, internal or
public), and requests — work items of behaviour ``request`` with their record (form version, answers, requester,
status, decision, result, routing trace, tracking token)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import PROJECTS_TABLE, TASKS_TABLE

from .constants import PPM_FORM_VERSIONS_TABLE, PPM_FORMS_TABLE, PPM_REQUESTS_TABLE

FORM_AUDIENCES = ('internal', 'public')
FORM_STATUSES = ('draft', 'published', 'closed')
REQUEST_STATUSES = (
    'submitted',
    'in_review',
    'needs_info',
    'accepted',
    'in_progress',
    'done',
    'rejected',
    'duplicate',
    'withdrawn',
    'cancelled',
)


def _tenant() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


def _organization() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


class PpmForm(UUIDv7AuditBase):
    """A request form: its draft definition (fields, logic, mapping, routing, title template) and settings."""

    __tablename__ = PPM_FORMS_TABLE
    __table_args__ = (
        CheckConstraint("audience in ('internal', 'public')", name='audience'),
        CheckConstraint("status in ('draft', 'published', 'closed')", name='status'),
        Index('ux_taas_ppm_forms_public_id', 'public_id', unique=True, postgresql_where=text('public_id is not null')),
    )

    tenant_id: Mapped[UUID] = _tenant()
    organization_id: Mapped[UUID] = _organization()
    project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'), nullable=True
    )
    """Null = an organization form."""
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'internal'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('0'))
    """Latest published version (0 = never published)."""
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    """``{schema_version, fields, title_template, routing}``."""
    public_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    queue_project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='set null'), nullable=True
    )
    request_type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """``confirmation``, ``triagers`` (user refs), ``notify_requester``."""
    owner: Mapped[str] = mapped_column(String(320), nullable=False)
    owner_user_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text('1'))
    """Optimistic version of the form row (draft and settings)."""
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class PpmFormVersion(UUIDv7AuditBase):
    """A published, immutable definition; requests keep the version they were submitted with."""

    __tablename__ = PPM_FORM_VERSIONS_TABLE
    __table_args__ = (Index('ux_taas_ppm_form_versions_version', 'form_id', 'version', unique=True),)

    tenant_id: Mapped[UUID] = _tenant()
    form_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{PPM_FORMS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_by: Mapped[str] = mapped_column(String(320), nullable=False)
    published_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class PpmRequest(UUIDv7AuditBase):
    """The request record of a work item (behaviour ``request``)."""

    __tablename__ = PPM_REQUESTS_TABLE
    __table_args__ = (
        CheckConstraint(
            "status in ('submitted', 'in_review', 'needs_info', 'accepted', 'in_progress', 'done', 'rejected',"
            " 'duplicate', 'withdrawn', 'cancelled')",
            name='status',
        ),
        Index('ux_taas_ppm_requests_task', 'task_id', unique=True),
        Index(
            'ux_taas_ppm_requests_idempotency',
            'form_id',
            'idempotency_key',
            unique=True,
            postgresql_where=text('idempotency_key is not null'),
        ),
        Index('ux_taas_ppm_requests_tracking', 'tracking_hash', unique=True, postgresql_where=text('tracking_hash is not null')),
        Index('ix_taas_ppm_requests_form', 'form_id', 'status'),
        Index('ix_taas_ppm_requests_requester', 'organization_id', 'requester_ref'),
    )

    tenant_id: Mapped[UUID] = _tenant()
    organization_id: Mapped[UUID] = _organization()
    task_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{TASKS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    form_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{PPM_FORMS_TABLE}.id', ondelete='cascade'), nullable=False
    )
    form_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    """A member's user ref (e-mail); null for an external requester."""
    requester_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requester_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_member: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    requester_locale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'submitted'"))
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    """``accepted_project`` · ``accepted_item`` · ``accepted_in_place`` · ``rejected`` · ``merged`` · ``withdrawn``."""
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    result_project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    result_task_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    duplicate_of: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """The original request's item when merged."""
    routing_trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tracking_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """SHA-256 of the requester's tracking token (the token itself is never stored)."""
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
