"""ppm: time tracking V2 — timesheets, time categories, entry + effort columns

Revision ID: 8e88de5c0d0e
Revises: 253f21d9f40e
Create Date: 2026-10-10 02:44:11.520786

"""

import warnings
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql.named_types as pg_types    # <--- Add this line.
from alembic import op
from db.migrations.utils import check_enum_exists    # <--- Add this line.
from db.models.types import JSONText              # <--- Add this line.
from advanced_alchemy.types import EncryptedString, EncryptedText, GUID, ORA_JSONB, DateTimeUTC, StoredObject, PasswordHash, FernetBackend
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

__all__ = ["downgrade", "upgrade", "schema_upgrades", "schema_downgrades", "data_upgrades", "data_downgrades"]

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
revision = '8e88de5c0d0e'
down_revision = '253f21d9f40e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()

def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()

def schema_upgrades() -> None:
    """Time tracking V2 (time-tracking-spec §3): categories, timesheets, entry + effort columns."""
    op.create_table('taas_ppm_time_categories',
    sa.Column('id', sa.GUID(length=16), nullable=False),
    sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
    sa.Column('organization_id', sa.GUID(length=16), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=16), server_default=sa.text("'internal'"), nullable=False),
    sa.Column('billable_allowed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.CheckConstraint("kind in ('project', 'internal')", name=op.f('ck_taas_ppm_time_categories_kind')),
    sa.ForeignKeyConstraint(['organization_id'], ['taas_organizations.id'], name=op.f('fk_taas_ppm_time_categories_organization_id_taas_organizations'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['tenant_id'], ['taas_tenants.id'], name=op.f('fk_taas_ppm_time_categories_tenant_id_taas_tenants'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_time_categories'))
    )
    with op.batch_alter_table('taas_ppm_time_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_taas_ppm_time_categories_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index('ux_taas_ppm_time_categories_key', ['organization_id', 'key'], unique=True)

    op.create_table('taas_ppm_timesheets',
    sa.Column('id', sa.GUID(length=16), nullable=False),
    sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
    sa.Column('organization_id', sa.GUID(length=16), nullable=False),
    sa.Column('user_id', sa.String(length=320), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=24), server_default=sa.text("'open'"), nullable=False),
    sa.Column('total_minutes', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('billable_minutes', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('submitted_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('approved_at', postgresql.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('reopen_reason', sa.Text(), nullable=True),
    sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.CheckConstraint("status in ('open', 'submitted', 'partially_approved', 'approved', 'rejected', 'reopened')", name=op.f('ck_taas_ppm_timesheets_status')),
    sa.ForeignKeyConstraint(['organization_id'], ['taas_organizations.id'], name=op.f('fk_taas_ppm_timesheets_organization_id_taas_organizations'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['tenant_id'], ['taas_tenants.id'], name=op.f('fk_taas_ppm_timesheets_tenant_id_taas_tenants'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_timesheets'))
    )
    with op.batch_alter_table('taas_ppm_timesheets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_taas_ppm_timesheets_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index('ux_taas_ppm_timesheets_week', ['organization_id', 'user_id', 'period_start'], unique=True)

    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('remaining_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('remaining_base_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('remaining_set_at', sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(sa.Column('remaining_set_by', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('rollup_estimated_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rollup_actual_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rollup_remaining_minutes', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('variance_alert_level', sa.TEXT(), nullable=True))

    with op.batch_alter_table('taas_timelogs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tenant_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('organization_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('entry_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('time_category_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('source', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('timesheet_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('locked_at', sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(sa.Column('reverses_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('correction_reason', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('needs_review', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.TEXT(), nullable=True))
        batch_op.create_index('ix_taas_timelogs_project_date', ['project_id', 'entry_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_taas_timelogs_timesheet_id'), ['timesheet_id'], unique=False)
        batch_op.create_index('ix_taas_timelogs_user_date', ['user_id', 'entry_date'], unique=False)
        batch_op.create_index('ux_taas_timelogs_running', ['user_id'], unique=True, postgresql_where=sa.text('is_recording and deleted_at is null'))


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('taas_timelogs', schema=None) as batch_op:
        batch_op.drop_index('ux_taas_timelogs_running', postgresql_where=sa.text('is_recording and deleted_at is null'))
        batch_op.drop_index('ix_taas_timelogs_user_date')
        batch_op.drop_index(batch_op.f('ix_taas_timelogs_timesheet_id'))
        batch_op.drop_index('ix_taas_timelogs_project_date')
        for column in (
            'created_by',
            'needs_review',
            'correction_reason',
            'reverses_id',
            'locked_at',
            'timesheet_id',
            'source',
            'time_category_id',
            'entry_date',
            'organization_id',
            'tenant_id',
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        for column in (
            'variance_alert_level',
            'rollup_remaining_minutes',
            'rollup_actual_minutes',
            'rollup_estimated_minutes',
            'remaining_set_by',
            'remaining_set_at',
            'remaining_base_minutes',
            'remaining_minutes',
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table('taas_ppm_timesheets', schema=None) as batch_op:
        batch_op.drop_index('ux_taas_ppm_timesheets_week')
        batch_op.drop_index(batch_op.f('ix_taas_ppm_timesheets_tenant_id'))
    op.drop_table('taas_ppm_timesheets')
    with op.batch_alter_table('taas_ppm_time_categories', schema=None) as batch_op:
        batch_op.drop_index('ux_taas_ppm_time_categories_key')
        batch_op.drop_index(batch_op.f('ix_taas_ppm_time_categories_tenant_id'))
    op.drop_table('taas_ppm_time_categories')


def data_upgrades() -> None:
    """Existing time logs: calendar day, lowercase status / kind, scope from their project, source ``manual``."""
    op.execute("update taas_timelogs set entry_date = log_date::date where entry_date is null and log_date is not null")
    op.execute("update taas_timelogs set status = lower(status) where status is not null and status <> lower(status)")
    op.execute("update taas_timelogs set timelog_type = 'regular' where timelog_type is null or timelog_type = 'Regular'")
    op.execute("update taas_timelogs set source = 'manual' where source is null")
    op.execute(
        "update taas_timelogs l set tenant_id = p.tenant_id, organization_id = p.organization_id "
        "from taas_projects p where p.id = l.project_id and l.tenant_id is null"
    )


def data_downgrades() -> None:
    """Nothing to undo (the columns go away)."""
