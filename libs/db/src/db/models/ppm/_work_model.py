"""PPM work model V2 (taas-specs/ppm/work-model/work-model-spec.md): the organization's item type library with
behaviours (Ppm-0802…0806), custom fields with bindings and typed values (Ppm-0850…0857) and generic approvals with
their approvers, append-only events and policies (Ppm-0865…0873).

Users are referenced like the rest of PPM (ADR-12): ``*_ref`` / ``user_ref`` hold an IAM user id or an e-mail.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.ews.constants import TASKS_TABLE

from .constants import (
    PPM_APPROVAL_APPROVERS_TABLE,
    PPM_APPROVAL_EVENTS_TABLE,
    PPM_APPROVAL_POLICIES_TABLE,
    PPM_APPROVALS_TABLE,
    PPM_CUSTOM_FIELD_BINDINGS_TABLE,
    PPM_CUSTOM_FIELD_VALUES_TABLE,
    PPM_CUSTOM_FIELDS_TABLE,
    PPM_ITEM_TYPES_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _organization_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )


class PpmItemType(UUIDv7AuditBase):
    """One item type of the organization's library (Ppm-0802): term, look, **behaviour** (§5.1) and defaults.
    Catalog types keep the key of the universal template; custom types get a new key."""

    __tablename__ = PPM_ITEM_TYPES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_item_types_key',
            'organization_id',
            'key',
            unique=True,
            postgresql_where=text('archived_at is null'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """``{locale: term}`` shown to readers of that locale."""
    group: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'work'")
    )
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    behaviour: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'task'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_checklist_template_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    origin: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'catalog'")
    )
    """``catalog`` (seeded from the universal template) · ``custom``."""
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )


class PpmCustomField(UUIDv7AuditBase):
    """A typed field definition of the organization (``project_id`` null) or of one project (Ppm-0850, Ppm-0851).
    The type never changes (Ppm-0855); select options keep stable ids in ``config.options``."""

    __tablename__ = PPM_CUSTOM_FIELDS_TABLE
    __table_args__ = (
        CheckConstraint(
            "type in ('text', 'textarea', 'number', 'money', 'date', 'select', 'multi_select',"
            " 'user', 'url', 'checkbox')",
            name='type',
        ),
        Index(
            'ux_taas_ppm_custom_fields_org_key',
            'organization_id',
            'key',
            unique=True,
            postgresql_where=text('project_id is null and archived_at is null'),
        ),
        Index(
            'ux_taas_ppm_custom_fields_project_key',
            'project_id',
            'key',
            unique=True,
            postgresql_where=text('project_id is not null and archived_at is null'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """``options`` ``[{id, label, color, order, archived}]``, ``decimals``, ``unit``, ``percent``, ``currency``
    (fixed) / ``currencies`` (allowed), ``multi`` (user), ``min`` / ``max``, ``max_length``, ``with_time``."""
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )


class PpmCustomFieldBinding(UUIDv7AuditBase):
    """Where a field shows (Ppm-0851, Ppm-0852): an item type in every project (``item_type_key``), an item type in
    one project (``item_type_key`` + ``project_id``) or every item of a project (``project_id``)."""

    __tablename__ = PPM_CUSTOM_FIELD_BINDINGS_TABLE
    __table_args__ = (
        CheckConstraint(
            "required in ('never', 'on_create', 'before_done')", name='required'
        ),
        CheckConstraint(
            'item_type_key is not null or project_id is not null', name='target'
        ),
        Index(
            'ix_taas_ppm_custom_field_bindings_target', 'project_id', 'item_type_key'
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    field_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_CUSTOM_FIELDS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    item_type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    required: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'never'")
    )
    default_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    on_create_form: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    on_card: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )


class PpmCustomFieldValue(UUIDv7AuditBase):
    """One value of one field on one item (typed columns, Ppm-0850; ``NUMERIC(38,18)`` for numbers and money,
    ADR-15)."""

    __tablename__ = PPM_CUSTOM_FIELD_VALUES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_ppm_custom_field_values_item', 'task_id', 'field_id', unique=True
        ),
        Index(
            'ix_taas_ppm_custom_field_values_refs',
            'value_refs',
            postgresql_using='gin',
        ),
        Index('ix_taas_ppm_custom_field_values_field', 'field_id', 'value_number'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    task_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{TASKS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    field_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_CUSTOM_FIELDS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    value_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_refs: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(320)), nullable=True
    )
    """Option ids (select / multi-select) or user refs (user)."""
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)


class PpmApproval(UUIDv7AuditBase):
    """One approval of a subject (Ppm-0865): ordered steps of approvers (``taas_ppm_approval_approvers``), a
    snapshot of the subject at request time (Ppm-0872), status §5.4."""

    __tablename__ = PPM_APPROVALS_TABLE
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'approved', 'rejected', 'changes_requested',"
            " 'cancelled', 'outdated')",
            name='status',
        ),
        Index('ix_taas_ppm_approvals_subject', 'subject_type', 'subject_id', 'status'),
        Index('ix_taas_ppm_approvals_project', 'project_id', 'status'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    project_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """``task`` · ``timesheet`` · ``expense_report`` · ``request`` · ``budget`` · ``stage_gate``."""
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_part: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    policy_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(320), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False, server_default=text('now()')
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    round: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    current_step: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )


class PpmApprovalApprover(UUIDv7AuditBase):
    """An approver of one step, resolved to a user at request time and frozen (Ppm-0866)."""

    __tablename__ = PPM_APPROVAL_APPROVERS_TABLE
    __table_args__ = (
        CheckConstraint(
            "decision in ('pending', 'approved', 'rejected', 'changes_requested', 'skipped')",
            name='decision',
        ),
        CheckConstraint("step_rule in ('any', 'all')", name='step_rule'),
        Index('ix_taas_ppm_approval_approvers_user', 'user_ref', 'decision'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    approval_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_APPROVALS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    step_rule: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'any'")
    )
    user_ref: Mapped[str] = mapped_column(String(320), nullable=False)
    resolved_from: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'user'")
    )
    decision: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    delegated_from: Mapped[str | None] = mapped_column(String(320), nullable=True)


class PpmApprovalEvent(UUIDv7Base):
    """Append-only history of an approval (Ppm-0871)."""

    __tablename__ = PPM_APPROVAL_EVENTS_TABLE

    tenant_id: Mapped[UUID] = _tenant_fk()
    approval_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{PPM_APPROVALS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    """``requested`` · ``approved`` · ``rejected`` · ``changes_requested`` · ``delegated`` · ``cancelled`` ·
    ``resubmitted`` · ``outdated`` · ``skipped``."""
    actor_ref: Mapped[str | None] = mapped_column(String(320), nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    round: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('1')
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False, server_default=text('now()')
    )


class PpmApprovalPolicy(UUIDv7AuditBase):
    """Who approves what (Ppm-0869): organization (``project_id`` null) or project, per subject type, conditions,
    steps ``[{name, rule, approvers: [{type: user | project_role | org_role | resolver, ref}]}]``."""

    __tablename__ = PPM_APPROVAL_POLICIES_TABLE

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = _organization_fk()
    project_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """``item_types`` (keys), ``min_amount`` + ``currency``, ``categories``."""
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    due_working_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_self_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('false')
    )
    position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text('0')
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
