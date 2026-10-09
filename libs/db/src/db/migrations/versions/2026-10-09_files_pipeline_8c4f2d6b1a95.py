"""files: processing pipeline, previews, local search index (File Manager F3)

- ``taas_file_versions``: pipeline state (``pipeline_*``), ``preview_status``, ``index_status``, ``meta`` — existing
  versions start ``pending`` (backfilled by the pipeline); versions of purged items are marked ``done`` / ``none``.
- ``taas_file_previews``: generated variants (``thumb`` · ``preview``) under ``derived/files/…``.
- ``taas_file_contents``: extracted text + generated ``tsvector`` (GIN) of the current versions.
- ``ix_taas_file_nodes_name_trgm``: trigram index on names (``pg_trgm``; skipped when the extension cannot be
  created — name search still works, slower).

Spec: taas-specs/files/ (file-manager-app-spec.md §6, §7, §9, files-architecture.md, decisions ADR-9 … ADR-13). Written by hand; mirrors
``db.models.files``.

Revision ID: 8c4f2d6b1a95
Revises: b3d9f1a2c4e7
Create Date: 2026-10-09 00:00:00.000000

"""

import warnings

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '8c4f2d6b1a95'
down_revision = 'b3d9f1a2c4e7'
branch_labels = None
depends_on = None


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


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f'{target}.id'],
        name=f'fk_{table}_{column}_{target}',
        ondelete='cascade',
    )


def schema_upgrades() -> None:
    op.add_column(
        'taas_file_versions',
        sa.Column('pipeline_status', sa.String(16), nullable=False, server_default='pending'),
    )
    op.add_column(
        'taas_file_versions',
        sa.Column('pipeline_attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'taas_file_versions',
        sa.Column('pipeline_at', DateTimeUTC(timezone=True), nullable=True),
    )
    op.add_column(
        'taas_file_versions', sa.Column('pipeline_error', sa.String(500), nullable=True)
    )
    op.add_column(
        'taas_file_versions',
        sa.Column('preview_status', sa.String(16), nullable=False, server_default='pending'),
    )
    op.add_column(
        'taas_file_versions',
        sa.Column('index_status', sa.String(16), nullable=False, server_default='pending'),
    )
    op.add_column(
        'taas_file_versions',
        sa.Column(
            'meta',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    for name, values in (
        ('pipeline_status', "'pending', 'running', 'done', 'failed'"),
        ('preview_status', "'pending', 'ready', 'none', 'failed'"),
        ('index_status', "'pending', 'ready', 'none', 'failed'"),
    ):
        op.create_check_constraint(
            f'ck_taas_file_versions_{name}', 'taas_file_versions', f'{name} in ({values})'
        )
    op.create_index(
        'ix_taas_file_versions_pipeline',
        'taas_file_versions',
        ['created_at'],
        postgresql_where=sa.text("pipeline_status in ('pending', 'running')"),
    )

    op.create_table(
        'taas_file_previews',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('node_id', GUID(length=16), nullable=False),
        sa.Column('version_id', GUID(length=16), nullable=False),
        sa.Column('variant', sa.String(16), nullable=False),
        sa.Column('key', sa.String(1024), nullable=False),
        sa.Column('mime', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('placeholder', sa.String(2048), nullable=True),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        _fk('taas_file_previews', 'tenant_id', 'taas_tenants'),
        _fk('taas_file_previews', 'node_id', 'taas_file_nodes'),
        _fk('taas_file_previews', 'version_id', 'taas_file_versions'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_previews'),
        sa.UniqueConstraint('version_id', 'variant', name='uq_taas_file_previews_variant'),
    )
    op.create_index('ix_taas_file_previews_tenant_id', 'taas_file_previews', ['tenant_id'])
    op.create_index('ix_taas_file_previews_node_id', 'taas_file_previews', ['node_id'])

    op.create_table(
        'taas_file_contents',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('node_id', GUID(length=16), nullable=False),
        sa.Column('version_id', GUID(length=16), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('chars', sa.Integer(), nullable=False),
        sa.Column('truncated', sa.Boolean(), nullable=False),
        sa.Column(
            'tsv',
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
            nullable=True,
        ),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        _fk('taas_file_contents', 'tenant_id', 'taas_tenants'),
        _fk('taas_file_contents', 'node_id', 'taas_file_nodes'),
        _fk('taas_file_contents', 'version_id', 'taas_file_versions'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_file_contents'),
        sa.UniqueConstraint('version_id', name='uq_taas_file_contents_version'),
    )
    op.create_index('ix_taas_file_contents_tenant_id', 'taas_file_contents', ['tenant_id'])
    op.create_index('ix_taas_file_contents_node_id', 'taas_file_contents', ['node_id'])
    op.create_index(
        'ix_taas_file_contents_tsv', 'taas_file_contents', ['tsv'], postgresql_using='gin'
    )

    # Trigram index on names (fast "name contains"): only where pg_trgm exists or can be created.
    op.execute(
        """
        DO $$
        BEGIN
          BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
          EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_trgm not available: %', SQLERRM;
          END;
          IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
            CREATE INDEX IF NOT EXISTS ix_taas_file_nodes_name_trgm
              ON taas_file_nodes USING gin (name gin_trgm_ops);
          END IF;
        END $$;
        """
    )


def data_upgrades() -> None:
    # Purged items have no storage objects any more: nothing to process.
    op.execute(
        """
        UPDATE taas_file_versions v
           SET pipeline_status = 'done', preview_status = 'none', index_status = 'none'
          FROM taas_file_nodes n
         WHERE n.id = v.node_id AND n.deleted_at IS NOT NULL
        """
    )


def data_downgrades() -> None:
    pass


def schema_downgrades() -> None:
    op.execute('DROP INDEX IF EXISTS ix_taas_file_nodes_name_trgm')
    op.drop_table('taas_file_contents')
    op.drop_table('taas_file_previews')
    op.drop_index('ix_taas_file_versions_pipeline', table_name='taas_file_versions')
    for name in ('pipeline_status', 'preview_status', 'index_status'):
        op.drop_constraint(f'ck_taas_file_versions_{name}', 'taas_file_versions')
    for column in (
        'meta',
        'index_status',
        'preview_status',
        'pipeline_error',
        'pipeline_at',
        'pipeline_attempts',
        'pipeline_status',
    ):
        op.drop_column('taas_file_versions', column)
