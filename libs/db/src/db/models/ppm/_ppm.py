"""PPM tables of the V1 foundations (taas-specs/ppm): organization settings and capability levels (Ppm-0009),
the audit / activity store (Ppm-0011, ADR-26), mentions (Ppm-0510), web links of projects and items (Ppm-0840),
My Work plans and personal settings (Ppm-0910…0914, ADR-18).

Users are referenced like the rest of PPM (ADR-12): ``*_ref`` columns hold an IAM user id or an e-mail; plans and
settings belong to the session user (``user_id``, always an IAM / development user id).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import (
    PPM_ATTACHMENTS_TABLE,
    PPM_AUDIT_EVENTS_TABLE,
    PPM_MENTIONS_TABLE,
    PPM_MY_WORK_PLANS_TABLE,
    PPM_SETTINGS_TABLE,
    PPM_USER_SETTINGS_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class PpmSettings(UUIDv7AuditBase):
    """PPM settings of one organization: capability level ⭐–⭐⭐⭐⭐ and single-capability overrides (Ppm-0009),
    plus the organization's PPM preferences (``settings``: time, finance, health, …). One row per organization."""

    __tablename__ = PPM_SETTINGS_TABLE
    __table_args__ = (
        CheckConstraint('level between 1 and 4', name='level'),
        Index('ux_taas_ppm_settings_organization', 'organization_id', unique=True),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('2')
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """``{capability key: true | false}`` — overrides of the level (capability map keys)."""
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class PpmAuditEvent(UUIDv7Base):
    """One domain change (ADR-25 envelope, Ppm-0008) kept for audit and the Activity tabs (ADR-26): append-only."""

    __tablename__ = PPM_AUDIT_EVENTS_TABLE
    __table_args__ = (
        Index(
            'ix_taas_ppm_audit_events_project', 'project_id', text('occurred_at DESC')
        ),
        Index(
            'ix_taas_ppm_audit_events_subject',
            'subject_type',
            'subject_id',
            text('occurred_at DESC'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    """Topic ``ppm.<entity>.<event>``."""
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'user'")
    )
    """``user`` · ``rule`` · ``agent`` · ``system``."""
    actor_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cause: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ui'")
    )
    """``ui`` · ``api`` · ``import`` · ``rule`` · ``ai`` · ``template`` · ``quick_add`` · ``system``."""
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """``{field: {from, to}}``."""
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """Event-specific payload (names, codes, ids) for the Activity text."""
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False, server_default=text('now()')
    )


class PpmMention(UUIDv7AuditBase):
    """A user mentioned in a comment or an item description (Ppm-0510); feeds notifications and My Work."""

    __tablename__ = PPM_MENTIONS_TABLE
    __table_args__ = (
        Index('ix_taas_ppm_mentions_user', 'user_ref'),
        Index('ix_taas_ppm_mentions_subject', 'subject_type', 'subject_id'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """``task`` · ``project``."""
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    user_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class PpmAttachment(UUIDv7AuditBase, SoftDeleteColumns):
    """A web link on a project or an item (Ppm-0840). Uploaded files are File Manager nodes in the project drive
    (File-0101 / File-0102), not rows here."""

    __tablename__ = PPM_ATTACHMENTS_TABLE
    __table_args__ = (
        CheckConstraint("kind in ('link', 'file')", name='kind'),
        Index('ix_taas_ppm_attachments_project', 'project_id', 'task_id'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    project_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'link'")
    )
    file_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    added_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class PpmMyWorkPlan(UUIDv7AuditBase):
    """My planned date, order and snooze of one My Work entry — private (Ppm-0914), never an event (Ppm-0008)."""

    __tablename__ = PPM_MY_WORK_PLANS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_my_work_plans_source',
            'user_id',
            'source_type',
            'source_id',
            unique=True,
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    """``task`` · ``checklist_item`` · ``mention`` · ``approval`` · ``request``."""
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_key: Mapped[float | None] = mapped_column(Float, nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )


class PpmUserSettings(UUIDv7AuditBase):
    """Personal PPM settings (My Work: week start, working days, day capacity, default view)."""

    __tablename__ = PPM_USER_SETTINGS_TABLE
    __table_args__ = (Index('ux_taas_ppm_user_settings_user', 'user_id', unique=True),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    user_id: Mapped[UUID] = mapped_column(GUID(length=16), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
