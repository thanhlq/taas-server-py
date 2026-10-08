"""knowledge: taas_kb_* (Knowledge Center spaces, page tree, revisions, attachments)

Spec: taas-specs/knowledge/ (K1 spaces & access, K2 pages & editor). Written by hand from
``db.models.knowledge``.

Revision ID: 5c2d8e4a1f63
Revises: 3f1a9c7e2b10
Create Date: 2026-10-08 00:00:00.000000

"""

import warnings
from typing import TYPE_CHECKING

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

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

# revision identifiers, used by Alembic.
revision = '5c2d8e4a1f63'
down_revision = '3f1a9c7e2b10'
branch_labels: 'str | Sequence[str] | None' = None
depends_on: 'str | Sequence[str] | None' = None


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


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
    ]


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f'{target}.id'],
        name=op.f(f'fk_{table}_{column}_{target}'),
        ondelete='cascade',
    )


def schema_upgrades() -> None:
    """schema upgrade migrations go here."""
    op.create_table(
        'taas_kb_spaces',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=60), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('icon', sa.String(length=40), nullable=True),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column('visibility', sa.String(length=16), nullable=False),
        sa.Column('include_sub_orgs', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        sa.Column('updated_by', sa.GUID(length=16), nullable=True),
        *_audit_columns(),
        sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint(
            "visibility IN ('tenant', 'organization', 'restricted')",
            name=op.f('ck_taas_kb_spaces_visibility'),
        ),
        _fk('taas_kb_spaces', 'organization_id', 'taas_organizations'),
        _fk('taas_kb_spaces', 'tenant_id', 'taas_tenants'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_kb_spaces')),
    )
    with op.batch_alter_table('taas_kb_spaces', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_kb_spaces_organization_id'),
            ['organization_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_spaces_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_kb_spaces_tenant_slug',
            ['tenant_id', 'slug'],
            unique=True,
            postgresql_where=sa.text('deleted_at IS NULL'),
        )

    op.create_table(
        'taas_kb_pages',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('space_id', sa.GUID(length=16), nullable=False),
        sa.Column('parent_id', sa.GUID(length=16), nullable=True),
        sa.Column('path', sa.String(length=512), nullable=False),
        sa.Column('depth', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('published_title', sa.String(length=200), nullable=True),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('owner_id', sa.GUID(length=16), nullable=True),
        sa.Column('review_interval_days', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('verified_by', sa.GUID(length=16), nullable=True),
        sa.Column('verified_until', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('draft_revision_id', sa.GUID(length=16), nullable=True),
        sa.Column('published_revision_id', sa.GUID(length=16), nullable=True),
        sa.Column('published_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('published_by', sa.GUID(length=16), nullable=True),
        sa.Column('search_text', sa.Text(), nullable=True),
        sa.Column('locked_by', sa.GUID(length=16), nullable=True),
        sa.Column('locked_until', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        sa.Column('updated_by', sa.GUID(length=16), nullable=True),
        *_audit_columns(),
        sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        _fk('taas_kb_pages', 'parent_id', 'taas_kb_pages'),
        _fk('taas_kb_pages', 'space_id', 'taas_kb_spaces'),
        _fk('taas_kb_pages', 'tenant_id', 'taas_tenants'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_kb_pages')),
    )
    with op.batch_alter_table('taas_kb_pages', schema=None) as batch_op:
        batch_op.create_index(
            'ix_taas_kb_pages_owner', ['tenant_id', 'owner_id'], unique=False
        )
        batch_op.create_index(
            'ix_taas_kb_pages_path',
            ['path'],
            unique=False,
            postgresql_ops={'path': 'text_pattern_ops'},
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_pages_space_id'), ['space_id'], unique=False
        )
        batch_op.create_index(
            'ix_taas_kb_pages_space_parent',
            ['space_id', 'parent_id', 'position'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_pages_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_kb_pages_space_slug',
            ['space_id', 'slug'],
            unique=True,
            postgresql_where=sa.text('deleted_at IS NULL'),
        )

    op.create_table(
        'taas_kb_page_revisions',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('space_id', sa.GUID(length=16), nullable=False),
        sa.Column('page_id', sa.GUID(length=16), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('doc', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('author_id', sa.GUID(length=16), nullable=True),
        sa.Column('published_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('published_by', sa.GUID(length=16), nullable=True),
        *_audit_columns(),
        _fk('taas_kb_page_revisions', 'page_id', 'taas_kb_pages'),
        _fk('taas_kb_page_revisions', 'space_id', 'taas_kb_spaces'),
        _fk('taas_kb_page_revisions', 'tenant_id', 'taas_tenants'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_kb_page_revisions')),
    )
    with op.batch_alter_table('taas_kb_page_revisions', schema=None) as batch_op:
        batch_op.create_index(
            'ix_taas_kb_page_revisions_page', ['page_id', 'created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_page_revisions_page_id'), ['page_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_page_revisions_space_id'), ['space_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_page_revisions_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_kb_attachments',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('space_id', sa.GUID(length=16), nullable=False),
        sa.Column('page_id', sa.GUID(length=16), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('mime', sa.String(length=128), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('key', sa.String(length=1024), nullable=False),
        sa.Column('checksum', sa.String(length=64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        *_audit_columns(),
        sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        _fk('taas_kb_attachments', 'page_id', 'taas_kb_pages'),
        _fk('taas_kb_attachments', 'space_id', 'taas_kb_spaces'),
        _fk('taas_kb_attachments', 'tenant_id', 'taas_tenants'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_kb_attachments')),
    )
    with op.batch_alter_table('taas_kb_attachments', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_kb_attachments_page_id'), ['page_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_attachments_space_id'), ['space_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_kb_attachments_tenant_id'), ['tenant_id'], unique=False
        )


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    op.drop_table('taas_kb_attachments')
    op.drop_table('taas_kb_page_revisions')
    op.drop_table('taas_kb_pages')
    op.drop_table('taas_kb_spaces')


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
