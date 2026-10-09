"""ppm: work model V2 — item type library, custom fields, approvals; task behaviour + recurrence

Tables taas_ppm_item_types, taas_ppm_custom_fields (+ bindings, values), taas_ppm_approvals (+ approvers, events,
policies); taas_tasks.behaviour (mirror of the item type, backfilled from the default mapping), recurrence_rule,
created_from_template_item_id; checklist templates get tenant_id + organization_id (taas-specs/ppm/work-model/work-model-spec.md).

Revision ID: b6c587d4a357
Revises: a6c3e8b1d742
Create Date: 2026-10-10 00:48:11.791105

"""

import warnings
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql.named_types as pg_types  # <--- Add this line.
from alembic import op
from db.migrations.utils import check_enum_exists  # <--- Add this line.
from db.models.types import JSONText  # <--- Add this line.
from advanced_alchemy.types import (
    EncryptedString,
    EncryptedText,
    GUID,
    ORA_JSONB,
    DateTimeUTC,
    StoredObject,
    PasswordHash,
    FernetBackend,
)
from advanced_alchemy.types.encrypted_string import PGCryptoBackend
from sqlalchemy import Text  # noqa: F401
from sqlalchemy.dialects import postgresql

try:
    from advanced_alchemy.types.password_hash.argon2 import Argon2Hasher
except ImportError:
    Argon2Hasher = Any  # type: ignore
try:
    from advanced_alchemy.types.password_hash.passlib import PasslibHasher
except ImportError:
    PasslibHasher = Any  # type: ignore
try:
    from advanced_alchemy.types.password_hash.pwdlib import PwdlibHasher
except ImportError:
    PwdlibHasher = Any  # type: ignore

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    'downgrade',
    'upgrade',
    'schema_upgrades',
    'schema_downgrades',
    'data_upgrades',
    'data_downgrades',
]

sa.GUID = GUID
sa.DateTimeUTC = DateTimeUTC
sa.ORA_JSONB = ORA_JSONB
sa.EncryptedString = EncryptedString
sa.EncryptedText = EncryptedText
sa.StoredObject = StoredObject
sa.PasswordHash = PasswordHash
sa.Argon2Hasher = Argon2Hasher
sa.PasslibHasher = PasslibHasher
sa.PwdlibHasher = PwdlibHasher
sa.FernetBackend = FernetBackend
sa.PGCryptoBackend = PGCryptoBackend

# revision identifiers, used by Alembic.
revision = 'b6c587d4a357'
down_revision = 'a6c3e8b1d742'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()


def schema_upgrades() -> None:
    """schema upgrade migrations go here."""
    op.create_table(
        'taas_ppm_approval_policies',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('project_id', sa.GUID(length=16), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('subject_type', sa.String(length=32), nullable=False),
        sa.Column(
            'conditions',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'steps',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column('due_working_days', sa.Integer(), nullable=True),
        sa.Column(
            'allow_self_approval',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('archived_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f(
                'fk_taas_ppm_approval_policies_organization_id_taas_organizations'
            ),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_approval_policies_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_approval_policies')),
    )
    with op.batch_alter_table('taas_ppm_approval_policies', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_policies_project_id'),
            ['project_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_policies_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_ppm_approvals',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('project_id', sa.GUID(length=16), nullable=True),
        sa.Column('subject_type', sa.String(length=32), nullable=False),
        sa.Column('subject_id', sa.String(length=64), nullable=False),
        sa.Column('subject_part', sa.String(length=64), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column(
            'subject_snapshot',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('policy_id', sa.GUID(length=16), nullable=True),
        sa.Column('requested_by', sa.String(length=320), nullable=False),
        sa.Column(
            'requested_at',
            sa.DateTimeUTC(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('due_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column(
            'status',
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column('round', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column(
            'current_step', sa.Integer(), server_default=sa.text('1'), nullable=False
        ),
        sa.Column('decided_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'approved', 'rejected', 'changes_requested', 'cancelled', 'outdated')",
            name=op.f('ck_taas_ppm_approvals_status'),
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f('fk_taas_ppm_approvals_organization_id_taas_organizations'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_approvals_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_approvals')),
    )
    with op.batch_alter_table('taas_ppm_approvals', schema=None) as batch_op:
        batch_op.create_index(
            'ix_taas_ppm_approvals_project', ['project_id', 'status'], unique=False
        )
        batch_op.create_index(
            'ix_taas_ppm_approvals_subject',
            ['subject_type', 'subject_id', 'status'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approvals_tenant_id'), ['tenant_id'], unique=False
        )

    op.create_table(
        'taas_ppm_custom_fields',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('project_id', sa.GUID(length=16), nullable=True),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=200), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'config',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('archived_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type in ('text', 'textarea', 'number', 'money', 'date', 'select', 'multi_select', 'user', 'url', 'checkbox')",
            name=op.f('ck_taas_ppm_custom_fields_type'),
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f('fk_taas_ppm_custom_fields_organization_id_taas_organizations'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_custom_fields_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_custom_fields')),
    )
    with op.batch_alter_table('taas_ppm_custom_fields', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_custom_fields_project_id'),
            ['project_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_custom_fields_tenant_id'),
            ['tenant_id'],
            unique=False,
        )
        batch_op.create_index(
            'ux_taas_ppm_custom_fields_org_key',
            ['organization_id', 'key'],
            unique=True,
            postgresql_where=sa.text('project_id is null and archived_at is null'),
        )
        batch_op.create_index(
            'ux_taas_ppm_custom_fields_project_key',
            ['project_id', 'key'],
            unique=True,
            postgresql_where=sa.text('project_id is not null and archived_at is null'),
        )

    op.create_table(
        'taas_ppm_item_types',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('term', sa.String(length=200), nullable=False),
        sa.Column(
            'translations',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'group',
            sa.String(length=16),
            server_default=sa.text("'work'"),
            nullable=False,
        ),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column(
            'behaviour',
            sa.String(length=16),
            server_default=sa.text("'task'"),
            nullable=False,
        ),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('default_checklist_template_id', sa.GUID(length=16), nullable=True),
        sa.Column(
            'origin',
            sa.String(length=8),
            server_default=sa.text("'catalog'"),
            nullable=False,
        ),
        sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('archived_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f('fk_taas_ppm_item_types_organization_id_taas_organizations'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_item_types_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_item_types')),
    )
    with op.batch_alter_table('taas_ppm_item_types', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_item_types_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_ppm_item_types_key',
            ['organization_id', 'key'],
            unique=True,
            postgresql_where=sa.text('archived_at is null'),
        )

    op.create_table(
        'taas_ppm_approval_approvers',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('approval_id', sa.GUID(length=16), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False),
        sa.Column('step_name', sa.String(length=120), nullable=True),
        sa.Column(
            'step_rule',
            sa.String(length=8),
            server_default=sa.text("'any'"),
            nullable=False,
        ),
        sa.Column('user_ref', sa.String(length=320), nullable=False),
        sa.Column(
            'resolved_from',
            sa.String(length=64),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column(
            'decision',
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column('decided_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('delegated_from', sa.String(length=320), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision in ('pending', 'approved', 'rejected', 'changes_requested', 'skipped')",
            name=op.f('ck_taas_ppm_approval_approvers_decision'),
        ),
        sa.CheckConstraint(
            "step_rule in ('any', 'all')",
            name=op.f('ck_taas_ppm_approval_approvers_step_rule'),
        ),
        sa.ForeignKeyConstraint(
            ['approval_id'],
            ['taas_ppm_approvals.id'],
            name=op.f('fk_taas_ppm_approval_approvers_approval_id_taas_ppm_approvals'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_approval_approvers_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_approval_approvers')),
    )
    with op.batch_alter_table('taas_ppm_approval_approvers', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_approvers_approval_id'),
            ['approval_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_approvers_tenant_id'),
            ['tenant_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_taas_ppm_approval_approvers_user',
            ['user_ref', 'decision'],
            unique=False,
        )

    op.create_table(
        'taas_ppm_approval_events',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('approval_id', sa.GUID(length=16), nullable=False),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('actor_ref', sa.String(length=320), nullable=True),
        sa.Column('step', sa.Integer(), nullable=True),
        sa.Column('round', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('subject_hash', sa.String(length=64), nullable=True),
        sa.Column(
            'occurred_at',
            sa.DateTimeUTC(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['approval_id'],
            ['taas_ppm_approvals.id'],
            name=op.f('fk_taas_ppm_approval_events_approval_id_taas_ppm_approvals'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_approval_events_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_approval_events')),
    )
    with op.batch_alter_table('taas_ppm_approval_events', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_events_approval_id'),
            ['approval_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_approval_events_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_ppm_custom_field_bindings',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('field_id', sa.GUID(length=16), nullable=False),
        sa.Column('item_type_key', sa.String(length=64), nullable=True),
        sa.Column('project_id', sa.GUID(length=16), nullable=True),
        sa.Column(
            'required',
            sa.String(length=16),
            server_default=sa.text("'never'"),
            nullable=False,
        ),
        sa.Column(
            'default_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column('section', sa.String(length=64), nullable=True),
        sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column(
            'on_create_form',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column(
            'on_card', sa.Boolean(), server_default=sa.text('false'), nullable=False
        ),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.CheckConstraint(
            "required in ('never', 'on_create', 'before_done')",
            name=op.f('ck_taas_ppm_custom_field_bindings_required'),
        ),
        sa.CheckConstraint(
            'item_type_key is not null or project_id is not null',
            name=op.f('ck_taas_ppm_custom_field_bindings_target'),
        ),
        sa.ForeignKeyConstraint(
            ['field_id'],
            ['taas_ppm_custom_fields.id'],
            name=op.f(
                'fk_taas_ppm_custom_field_bindings_field_id_taas_ppm_custom_fields'
            ),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f(
                'fk_taas_ppm_custom_field_bindings_organization_id_taas_organizations'
            ),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_custom_field_bindings_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_custom_field_bindings')),
    )
    with op.batch_alter_table(
        'taas_ppm_custom_field_bindings', schema=None
    ) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_custom_field_bindings_field_id'),
            ['field_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_taas_ppm_custom_field_bindings_target',
            ['project_id', 'item_type_key'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_custom_field_bindings_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_ppm_custom_field_values',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('task_id', sa.GUID(length=16), nullable=False),
        sa.Column('field_id', sa.GUID(length=16), nullable=False),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('value_number', sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column('value_currency', sa.String(length=8), nullable=True),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.Column('value_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('value_bool', sa.Boolean(), nullable=True),
        sa.Column('value_refs', postgresql.ARRAY(sa.String(length=320)), nullable=True),
        sa.Column('updated_by', sa.String(length=320), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['field_id'],
            ['taas_ppm_custom_fields.id'],
            name=op.f(
                'fk_taas_ppm_custom_field_values_field_id_taas_ppm_custom_fields'
            ),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['task_id'],
            ['taas_tasks.id'],
            name=op.f('fk_taas_ppm_custom_field_values_task_id_taas_tasks'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_ppm_custom_field_values_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_custom_field_values')),
    )
    with op.batch_alter_table('taas_ppm_custom_field_values', schema=None) as batch_op:
        batch_op.create_index(
            'ix_taas_ppm_custom_field_values_field',
            ['field_id', 'value_number'],
            unique=False,
        )
        batch_op.create_index(
            'ix_taas_ppm_custom_field_values_refs',
            ['value_refs'],
            unique=False,
            postgresql_using='gin',
        )
        batch_op.create_index(
            batch_op.f('ix_taas_ppm_custom_field_values_tenant_id'),
            ['tenant_id'],
            unique=False,
        )
        batch_op.create_index(
            'ux_taas_ppm_custom_field_values_item', ['task_id', 'field_id'], unique=True
        )

    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('behaviour', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('recurrence_rule', sa.TEXT(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'created_from_template_item_id', sa.GUID(length=16), nullable=True
            )
        )
        batch_op.create_index(
            batch_op.f('ix_taas_tasks_behaviour'), ['behaviour'], unique=False
        )
    with op.batch_alter_table('taas_checklist_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tenant_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(
            sa.Column('organization_id', sa.GUID(length=16), nullable=True)
        )
        batch_op.create_index(
            batch_op.f('ix_taas_checklist_templates_tenant_id'),
            ['tenant_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_checklist_templates_organization_id'),
            ['organization_id'],
            unique=False,
        )


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('taas_checklist_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_checklist_templates_organization_id'))
        batch_op.drop_index(batch_op.f('ix_taas_checklist_templates_tenant_id'))
        batch_op.drop_column('organization_id')
        batch_op.drop_column('tenant_id')
    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_tasks_behaviour'))
        batch_op.drop_column('created_from_template_item_id')
        batch_op.drop_column('recurrence_rule')
        batch_op.drop_column('behaviour')

    with op.batch_alter_table('taas_ppm_custom_field_values', schema=None) as batch_op:
        batch_op.drop_index('ux_taas_ppm_custom_field_values_item')
        batch_op.drop_index(batch_op.f('ix_taas_ppm_custom_field_values_tenant_id'))
        batch_op.drop_index(
            'ix_taas_ppm_custom_field_values_refs', postgresql_using='gin'
        )
        batch_op.drop_index('ix_taas_ppm_custom_field_values_field')

    op.drop_table('taas_ppm_custom_field_values')
    with op.batch_alter_table(
        'taas_ppm_custom_field_bindings', schema=None
    ) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_ppm_custom_field_bindings_tenant_id'))
        batch_op.drop_index('ix_taas_ppm_custom_field_bindings_target')
        batch_op.drop_index(batch_op.f('ix_taas_ppm_custom_field_bindings_field_id'))

    op.drop_table('taas_ppm_custom_field_bindings')
    with op.batch_alter_table('taas_ppm_approval_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_events_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_events_approval_id'))

    op.drop_table('taas_ppm_approval_events')
    with op.batch_alter_table('taas_ppm_approval_approvers', schema=None) as batch_op:
        batch_op.drop_index('ix_taas_ppm_approval_approvers_user')
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_approvers_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_approvers_approval_id'))

    op.drop_table('taas_ppm_approval_approvers')
    with op.batch_alter_table('taas_ppm_item_types', schema=None) as batch_op:
        batch_op.drop_index(
            'ux_taas_ppm_item_types_key',
            postgresql_where=sa.text('archived_at is null'),
        )
        batch_op.drop_index(batch_op.f('ix_taas_ppm_item_types_tenant_id'))

    op.drop_table('taas_ppm_item_types')
    with op.batch_alter_table('taas_ppm_custom_fields', schema=None) as batch_op:
        batch_op.drop_index(
            'ux_taas_ppm_custom_fields_project_key',
            postgresql_where=sa.text('project_id is not null and archived_at is null'),
        )
        batch_op.drop_index(
            'ux_taas_ppm_custom_fields_org_key',
            postgresql_where=sa.text('project_id is null and archived_at is null'),
        )
        batch_op.drop_index(batch_op.f('ix_taas_ppm_custom_fields_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_ppm_custom_fields_project_id'))

    op.drop_table('taas_ppm_custom_fields')
    with op.batch_alter_table('taas_ppm_approvals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approvals_tenant_id'))
        batch_op.drop_index('ix_taas_ppm_approvals_subject')
        batch_op.drop_index('ix_taas_ppm_approvals_project')

    op.drop_table('taas_ppm_approvals')
    with op.batch_alter_table('taas_ppm_approval_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_policies_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_ppm_approval_policies_project_id'))

    op.drop_table('taas_ppm_approval_policies')


def data_upgrades() -> None:
    """Behaviour of existing items from the default mapping of their item type key (work-model §5.1)."""
    op.execute(
        """
        update taas_tasks set behaviour = case
            when work_item_type = 'milestone' then 'milestone'
            when work_item_type = 'deliverable' then 'deliverable'
            when work_item_type in ('risk', 'risk_assessment') then 'risk'
            when work_item_type in ('issue', 'incident') then 'issue'
            when work_item_type in ('decision', 'assumption') then work_item_type
            when work_item_type like '%request' then 'request'
            when work_item_type like '%approval' then 'approval'
            else 'task' end
        where behaviour is null
        """
    )


def data_downgrades() -> None:
    """Nothing to undo (the column goes away)."""
