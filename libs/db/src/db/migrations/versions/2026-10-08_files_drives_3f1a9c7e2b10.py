"""files: taas_file_* (File Manager drives, folder / file tree, versions, activity, stars)

Spec: taas-specs/files/ (file-manager-app-spec.md §7, roadmap F1). Written by hand (autogenerate also picks
unrelated drift); mirrors ``db.models.files``.

Revision ID: 3f1a9c7e2b10
Revises: 9b3e61d4a7c2
Create Date: 2026-10-08 00:00:00.000000

"""

import warnings

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '3f1a9c7e2b10'
down_revision = '9b3e61d4a7c2'
branch_labels = None
depends_on = None

_ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        schema_upgrades()
        data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        data_downgrades()
        schema_downgrades()


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', DateTimeUTC(timezone=True), nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ['tenant_id'],
        ['taas_tenants.id'],
        name=f'fk_{table}_tenant_id_taas_tenants',
        ondelete='cascade',
    )


def schema_upgrades() -> None:
    op.create_table(
        'taas_file_drives',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('organization_id', GUID(length=16), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('owner_id', GUID(length=16), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('color', sa.String(length=32), nullable=True),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', GUID(length=16), nullable=True),
        *_audit_columns(),
        sa.Column('deleted_at', DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ('organization', 'shared', 'personal')",
            name='ck_taas_file_drives_kind',
        ),
        sa.CheckConstraint(
            "(kind = 'personal') = (organization_id is null)",
            name='ck_taas_file_drives_owner',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name='fk_taas_file_drives_organization_id_taas_organizations',
            ondelete='cascade',
        ),
        _tenant_fk('taas_file_drives'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_drives'),
    )
    op.create_index('ix_taas_file_drives_tenant_id', 'taas_file_drives', ['tenant_id'])
    op.create_index(
        'ix_taas_file_drives_organization_id', 'taas_file_drives', ['organization_id']
    )
    op.create_index('ix_taas_file_drives_owner_id', 'taas_file_drives', ['owner_id'])
    op.create_index(
        'ux_taas_file_drives_organization',
        'taas_file_drives',
        ['organization_id'],
        unique=True,
        postgresql_where=sa.text("kind = 'organization' AND deleted_at IS NULL"),
    )
    op.create_index(
        'ux_taas_file_drives_personal',
        'taas_file_drives',
        ['tenant_id', 'owner_id'],
        unique=True,
        postgresql_where=sa.text("kind = 'personal' AND deleted_at IS NULL"),
    )

    op.create_table(
        'taas_file_nodes',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('drive_id', GUID(length=16), nullable=False),
        sa.Column('parent_id', GUID(length=16), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('path', sa.String(length=1024), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('color', sa.String(length=32), nullable=True),
        sa.Column('current_version_id', GUID(length=16), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('mime', sa.String(length=255), nullable=True),
        sa.Column('ext', sa.String(length=16), nullable=True),
        sa.Column('created_by', GUID(length=16), nullable=True),
        sa.Column('updated_by', GUID(length=16), nullable=True),
        sa.Column('trashed_at', DateTimeUTC(timezone=True), nullable=True),
        sa.Column('trashed_by', GUID(length=16), nullable=True),
        sa.Column('trash_root_id', GUID(length=16), nullable=True),
        *_audit_columns(),
        sa.Column('deleted_at', DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ('folder', 'file')", name='ck_taas_file_nodes_kind'
        ),
        sa.ForeignKeyConstraint(
            ['drive_id'],
            ['taas_file_drives.id'],
            name='fk_taas_file_nodes_drive_id_taas_file_drives',
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['parent_id'],
            ['taas_file_nodes.id'],
            name='fk_taas_file_nodes_parent_id_taas_file_nodes',
            ondelete='cascade',
        ),
        _tenant_fk('taas_file_nodes'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_nodes'),
    )
    op.create_index('ix_taas_file_nodes_tenant_id', 'taas_file_nodes', ['tenant_id'])
    op.create_index('ix_taas_file_nodes_drive_id', 'taas_file_nodes', ['drive_id'])
    op.create_index(
        'ix_taas_file_nodes_trash_root_id', 'taas_file_nodes', ['trash_root_id']
    )
    op.create_index(
        'ix_taas_file_nodes_drive_parent', 'taas_file_nodes', ['drive_id', 'parent_id']
    )
    op.create_index(
        'ix_taas_file_nodes_drive_updated',
        'taas_file_nodes',
        ['drive_id', 'updated_at'],
    )
    op.create_index(
        'ix_taas_file_nodes_path',
        'taas_file_nodes',
        ['path'],
        postgresql_ops={'path': 'varchar_pattern_ops'},
    )
    op.create_index(
        'ux_taas_file_nodes_name',
        'taas_file_nodes',
        [
            'drive_id',
            sa.literal_column(f'coalesce(parent_id, {_ZERO_UUID})'),
            sa.literal_column('lower(name)'),
        ],
        unique=True,
        postgresql_where=sa.text('trashed_at IS NULL AND deleted_at IS NULL'),
    )

    op.create_table(
        'taas_file_versions',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('node_id', GUID(length=16), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=1024), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('mime', sa.String(length=255), nullable=False),
        sa.Column('checksum', sa.String(length=64), nullable=True),
        sa.Column('comment', sa.String(length=1000), nullable=True),
        sa.Column('scan_status', sa.String(length=16), nullable=False),
        sa.Column('restored_from', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', GUID(length=16), nullable=True),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "scan_status in ('pending', 'clean', 'infected', 'skipped', 'failed')",
            name='ck_taas_file_versions_scan_status',
        ),
        sa.ForeignKeyConstraint(
            ['node_id'],
            ['taas_file_nodes.id'],
            name='fk_taas_file_versions_node_id_taas_file_nodes',
            ondelete='cascade',
        ),
        _tenant_fk('taas_file_versions'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_versions'),
        sa.UniqueConstraint('node_id', 'number', name='uq_taas_file_versions_number'),
    )
    op.create_index(
        'ix_taas_file_versions_tenant_id', 'taas_file_versions', ['tenant_id']
    )
    op.create_index('ix_taas_file_versions_node_id', 'taas_file_versions', ['node_id'])

    op.create_table(
        'taas_file_activity',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('drive_id', GUID(length=16), nullable=False),
        sa.Column('node_id', GUID(length=16), nullable=True),
        sa.Column('actor_id', GUID(length=16), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['drive_id'],
            ['taas_file_drives.id'],
            name='fk_taas_file_activity_drive_id_taas_file_drives',
            ondelete='cascade',
        ),
        _tenant_fk('taas_file_activity'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_activity'),
    )
    op.create_index(
        'ix_taas_file_activity_tenant_id', 'taas_file_activity', ['tenant_id']
    )
    op.create_index(
        'ix_taas_file_activity_drive', 'taas_file_activity', ['drive_id', 'created_at']
    )
    op.create_index(
        'ix_taas_file_activity_node', 'taas_file_activity', ['node_id', 'created_at']
    )
    op.create_index(
        'ix_taas_file_activity_actor',
        'taas_file_activity',
        ['tenant_id', 'actor_id', 'created_at'],
    )

    op.create_table(
        'taas_file_stars',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('user_id', GUID(length=16), nullable=False),
        sa.Column('node_id', GUID(length=16), nullable=False),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ['node_id'],
            ['taas_file_nodes.id'],
            name='fk_taas_file_stars_node_id_taas_file_nodes',
            ondelete='cascade',
        ),
        _tenant_fk('taas_file_stars'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_stars'),
        sa.UniqueConstraint('user_id', 'node_id', name='uq_taas_file_stars_user_node'),
    )
    op.create_index('ix_taas_file_stars_tenant_id', 'taas_file_stars', ['tenant_id'])
    op.create_index('ix_taas_file_stars_user_id', 'taas_file_stars', ['user_id'])
    op.create_index('ix_taas_file_stars_node_id', 'taas_file_stars', ['node_id'])


def schema_downgrades() -> None:
    for table in (
        'taas_file_stars',
        'taas_file_activity',
        'taas_file_versions',
        'taas_file_nodes',
        'taas_file_drives',
    ):
        op.drop_table(table)


def data_upgrades() -> None:
    """No seed data: drives are created lazily (organization drive, My files) or by users (shared drives)."""


def data_downgrades() -> None:
    """Nothing to undo."""
