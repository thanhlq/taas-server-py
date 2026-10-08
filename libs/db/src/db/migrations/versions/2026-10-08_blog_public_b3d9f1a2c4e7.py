"""blog public: post addresses (slug_auto, former_slugs), releases, published media

Blog milestone B3 core (taas-specs/blog/blog-publishing-spec.md §2 / §3): ``taas_blog_posts.slug_auto`` (the slug
follows the title until the first publication, Blog-0107) and ``former_slugs`` (301 after a change, Blog-0108);
``taas_blog_releases`` (immutable index snapshots read by the site renderer) + ``taas_blog_blogs.live_release_id``;
``taas_blog_post_revisions.assets`` / ``cdn_origin`` (media of a published body with their CDN URLs).
Backfill: ``slug_auto`` = the post was never published.

Revision ID: b3d9f1a2c4e7
Revises: 7e4b2a9d6c15
Create Date: 2026-10-08 14:00:00.000000

"""

import warnings

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

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
revision = 'b3d9f1a2c4e7'
down_revision = '7e4b2a9d6c15'
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
    with op.batch_alter_table('taas_blog_posts', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'slug_auto',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                'former_slugs',
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            )
        )
    with op.batch_alter_table('taas_blog_post_revisions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('assets', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )
        batch_op.add_column(sa.Column('cdn_origin', sa.Text(), nullable=True))
    with op.batch_alter_table('taas_blog_blogs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('live_release_id', sa.GUID(length=16), nullable=True)
        )

    op.create_table(
        'taas_blog_releases',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_releases_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_releases_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_releases')),
        sa.UniqueConstraint('blog_id', 'version', name='uq_taas_blog_releases_version'),
    )
    with op.batch_alter_table('taas_blog_releases', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_releases_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_releases_tenant_id'), ['tenant_id'], unique=False
        )


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('taas_blog_releases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_releases_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_releases_blog_id'))
    op.drop_table('taas_blog_releases')
    with op.batch_alter_table('taas_blog_blogs', schema=None) as batch_op:
        batch_op.drop_column('live_release_id')
    with op.batch_alter_table('taas_blog_post_revisions', schema=None) as batch_op:
        batch_op.drop_column('cdn_origin')
        batch_op.drop_column('assets')
    with op.batch_alter_table('taas_blog_posts', schema=None) as batch_op:
        batch_op.drop_column('former_slugs')
        batch_op.drop_column('slug_auto')


def data_upgrades() -> None:
    """Posts published once keep their slug (Blog-0108); the others follow their title (Blog-0107)."""
    op.execute(
        'update taas_blog_posts set slug_auto = (published_at is null) '
        'where slug_auto is distinct from (published_at is null)'
    )


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
