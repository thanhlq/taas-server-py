"""PPM automation (taas-specs/ppm/automation/automation-spec.md Part B §3): user rules WHEN trigger · IF conditions ·
THEN actions, run as their owner, and their runs (log, undo, idempotency per occurrence). System rules stay in code
(``ews.ppm._notify``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import GUID
from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import PROJECTS_TABLE

from .constants import PPM_AUTOMATION_RULES_TABLE, PPM_AUTOMATION_RUNS_TABLE

RULE_STATUSES = ('active', 'paused', 'disabled')
TRIGGER_TYPES = ('event', 'relative', 'schedule')
RUN_STATUSES = (
    'succeeded',
    'skipped',
    'failed',
    'throttled',
    'loop_blocked',
    'dry_run',
    'undone',
)


class PpmAutomationRule(UUIDv7AuditBase):
    """A project rule (organization rules: V3): trigger, conditions and actions as JSON, validated on save."""

    __tablename__ = PPM_AUTOMATION_RULES_TABLE
    __table_args__ = (
        CheckConstraint("status in ('active', 'paused', 'disabled')", name='status'),
        CheckConstraint(
            "trigger_type in ('event', 'relative', 'schedule')", name='trigger_type'
        ),
        CheckConstraint("scope_type in ('project', 'organization')", name='scope_type'),
        Index(
            'ix_taas_ppm_automation_rules_event',
            'organization_id',
            'trigger_event',
            'status',
        ),
        Index(
            'ix_taas_ppm_automation_rules_due',
            'next_run_at',
            postgresql_where=text("status = 'active'"),
        ),
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
    scope_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'project'")
    )
    project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PROJECTS_TABLE}.id', ondelete='cascade'),
        nullable=True,
        index=True,
    )
    item_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    """Item type keys the rule applies to (null = every type)."""
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'disabled'")
    )
    owner: Mapped[str] = mapped_column(String(320), nullable=False)
    """The user the rule runs as (e-mail ref, like other PPM user columns)."""
    owner_user_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(String(80), nullable=True)
    """Event topic of an event trigger (indexed lookup of candidate rules)."""
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    """Consecutive failed runs (3 → paused)."""
    next_run_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    """Next scan of a relative / scheduled rule (UTC)."""
    last_run_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class PpmAutomationRun(UUIDv7AuditBase):
    """One evaluation of a rule for one occurrence (event, item × date, schedule instant): status, per-action results
    with before / after values (undo), duration."""

    __tablename__ = PPM_AUTOMATION_RUNS_TABLE
    __table_args__ = (
        CheckConstraint(
            "status in ('succeeded', 'skipped', 'failed', 'throttled', 'loop_blocked', 'dry_run', 'undone')",
            name='status',
        ),
        CheckConstraint("mode in ('live', 'test')", name='mode'),
        Index(
            'ux_taas_ppm_automation_runs_occurrence',
            'rule_id',
            'occurrence_key',
            unique=True,
            postgresql_where=text("mode = 'live'"),
        ),
        Index('ix_taas_ppm_automation_runs_rule', 'rule_id', text('created_at DESC')),
        Index('ix_taas_ppm_automation_runs_subject', 'subject_type', 'subject_id'),
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
    rule_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_AUTOMATION_RULES_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    depth: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    mode: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'live'")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    """Each condition with its result (dry-runs and skipped runs explain themselves)."""
    actions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """``[{type, target, before, after, status, error}]``."""
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    undone_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
