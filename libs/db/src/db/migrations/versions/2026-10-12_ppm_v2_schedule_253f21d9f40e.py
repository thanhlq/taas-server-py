"""ppm: schedule V2 — phases, work item links (dependencies), item schedule fields

Tables taas_ppm_phases, taas_ppm_work_item_links; taas_tasks.phase_id, duration_days, schedule_mode, constraint_type,
constraint_date, started_at; taas_projects.schedule_version (taas-specs/ppm/schedule/schedule-spec.md §3).

Revision ID: 253f21d9f40e
Revises: b6c587d4a357
Create Date: 2026-10-10 01:28:30.268055

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
revision = '253f21d9f40e'
down_revision = 'b6c587d4a357'
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
    """schema upgrade migrations go here."""
    op.create_table('taas_ppm_phases',
    sa.Column('id', sa.GUID(length=16), nullable=False),
    sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
    sa.Column('project_id', sa.GUID(length=16), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('color', sa.String(length=16), nullable=True),
    sa.Column('position', sa.Float(), server_default=sa.text('0'), nullable=False),
    sa.Column('planned_start', sa.Date(), nullable=True),
    sa.Column('planned_finish', sa.Date(), nullable=True),
    sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['taas_projects.id'], name=op.f('fk_taas_ppm_phases_project_id_taas_projects'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['tenant_id'], ['taas_tenants.id'], name=op.f('fk_taas_ppm_phases_tenant_id_taas_tenants'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_phases'))
    )
    with op.batch_alter_table('taas_ppm_phases', schema=None) as batch_op:
        batch_op.create_index('ix_taas_ppm_phases_project', ['project_id', 'position'], unique=False)
        batch_op.create_index(batch_op.f('ix_taas_ppm_phases_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('taas_ppm_work_item_links',
    sa.Column('id', sa.GUID(length=16), nullable=False),
    sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
    sa.Column('organization_id', sa.GUID(length=16), nullable=False),
    sa.Column('source_task_id', sa.GUID(length=16), nullable=False),
    sa.Column('target_task_id', sa.GUID(length=16), nullable=False),
    sa.Column('source_project_id', sa.GUID(length=16), nullable=False),
    sa.Column('target_project_id', sa.GUID(length=16), nullable=False),
    sa.Column('type', sa.String(length=16), server_default=sa.text("'fs'"), nullable=False),
    sa.Column('lag_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_by', sa.String(length=320), nullable=True),
    sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
    sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
    sa.CheckConstraint("type in ('fs', 'ss', 'ff', 'sf', 'relates', 'duplicates', 'blocks')", name=op.f('ck_taas_ppm_work_item_links_type')),
    sa.CheckConstraint('source_task_id <> target_task_id', name=op.f('ck_taas_ppm_work_item_links_not_self')),
    sa.ForeignKeyConstraint(['organization_id'], ['taas_organizations.id'], name=op.f('fk_taas_ppm_work_item_links_organization_id_taas_organizations'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['source_task_id'], ['taas_tasks.id'], name=op.f('fk_taas_ppm_work_item_links_source_task_id_taas_tasks'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['target_task_id'], ['taas_tasks.id'], name=op.f('fk_taas_ppm_work_item_links_target_task_id_taas_tasks'), ondelete='cascade'),
    sa.ForeignKeyConstraint(['tenant_id'], ['taas_tenants.id'], name=op.f('fk_taas_ppm_work_item_links_tenant_id_taas_tenants'), ondelete='cascade'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_ppm_work_item_links'))
    )
    with op.batch_alter_table('taas_ppm_work_item_links', schema=None) as batch_op:
        batch_op.create_index('ix_taas_ppm_work_item_links_project', ['source_project_id'], unique=False)
        batch_op.create_index('ix_taas_ppm_work_item_links_source', ['source_task_id'], unique=False)
        batch_op.create_index('ix_taas_ppm_work_item_links_target', ['target_task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_taas_ppm_work_item_links_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index('ux_taas_ppm_work_item_links_pair', [sa.literal_column('least(source_task_id, target_task_id)'), sa.literal_column('greatest(source_task_id, target_task_id)')], unique=True, postgresql_where=sa.text("deleted_at is null and type in ('fs', 'ss', 'ff', 'sf')"))
    with op.batch_alter_table('taas_projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schedule_version', sa.Integer(), server_default=sa.text('0'), nullable=False))
    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phase_id', sa.GUID(length=16), nullable=True))
        batch_op.add_column(sa.Column('duration_days', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('schedule_mode', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('constraint_type', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('constraint_date', sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(sa.Column('started_at', sa.TIMESTAMP(), nullable=True))
        batch_op.create_index(batch_op.f('ix_taas_tasks_phase_id'), ['phase_id'], unique=False)


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('taas_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_tasks_phase_id'))
        batch_op.drop_column('started_at')
        batch_op.drop_column('constraint_date')
        batch_op.drop_column('constraint_type')
        batch_op.drop_column('schedule_mode')
        batch_op.drop_column('duration_days')
        batch_op.drop_column('phase_id')
    with op.batch_alter_table('taas_projects', schema=None) as batch_op:
        batch_op.drop_column('schedule_version')
    with op.batch_alter_table('taas_ppm_work_item_links', schema=None) as batch_op:
        batch_op.drop_index('ux_taas_ppm_work_item_links_pair', postgresql_where=sa.text("deleted_at is null and type in ('fs', 'ss', 'ff', 'sf')"))
        batch_op.drop_index(batch_op.f('ix_taas_ppm_work_item_links_tenant_id'))
        batch_op.drop_index('ix_taas_ppm_work_item_links_target')
        batch_op.drop_index('ix_taas_ppm_work_item_links_source')
        batch_op.drop_index('ix_taas_ppm_work_item_links_project')

    op.drop_table('taas_ppm_work_item_links')
    with op.batch_alter_table('taas_ppm_phases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_ppm_phases_tenant_id'))
        batch_op.drop_index('ix_taas_ppm_phases_project')

    op.drop_table('taas_ppm_phases')


def data_upgrades() -> None:
    """Milestones get one date (start = due) and no estimate (behaviour ``milestone``)."""
    op.execute(
        "update taas_tasks set start_date = coalesce(due_date, start_date), due_date = coalesce(due_date, start_date), "
        "estimated_minutes = null where behaviour = 'milestone'"
    )


def data_downgrades() -> None:
    """Nothing to undo."""
