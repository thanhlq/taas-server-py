"""blog posts: taas_blog_* (blogs, posts + revisions, categories, tags, author profiles)

Blog app milestone B1 (taas-specs/blog/blog-app-spec.md §3, roadmap B1 / B2): blogs of an organization, posts whose
body is the Site Builder document (revisions: draft = working copy, published = live), the editorial status
(``draft`` → ``in_review`` → ``scheduled`` → ``published`` → ``unpublished`` · ``archived``), flat ordered
categories, tags and author profiles (optional user, guest authors). Every table carries ``tenant_id``.

Revision ID: 7e4b2a9d6c15
Revises: 5c2d8e4a1f63
Create Date: 2026-10-08 09:00:00.000000

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
revision = '7e4b2a9d6c15'
down_revision = '5c2d8e4a1f63'
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
        'taas_blog_blogs',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('organization_id', sa.GUID(length=16), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('locale', sa.String(length=16), nullable=False),
        sa.Column('mount', sa.String(length=16), nullable=False),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mount in ('system', 'site')", name=op.f('ck_taas_blog_blogs_mount')
        ),
        sa.CheckConstraint(
            "status in ('active', 'archived')", name=op.f('ck_taas_blog_blogs_status')
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name=op.f('fk_taas_blog_blogs_organization_id_taas_organizations'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_blogs_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_blogs')),
    )
    with op.batch_alter_table('taas_blog_blogs', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_blogs_organization_id'),
            ['organization_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_blogs_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_blog_blogs_org_slug',
            ['organization_id', 'slug'],
            unique=True,
            postgresql_where=sa.text('deleted_at IS NULL'),
        )

    op.create_table(
        'taas_blog_categories',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('seo', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_categories_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_categories_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_categories')),
        sa.UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_categories_slug'),
    )
    with op.batch_alter_table('taas_blog_categories', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_categories_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_categories_tenant_id'), ['tenant_id'], unique=False
        )

    op.create_table(
        'taas_blog_tags',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_tags_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_tags_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_tags')),
        sa.UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_tags_slug'),
    )
    with op.batch_alter_table('taas_blog_tags', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_tags_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_tags_tenant_id'), ['tenant_id'], unique=False
        )

    op.create_table(
        'taas_blog_authors',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=False),
        sa.Column('avatar_asset_id', sa.GUID(length=16), nullable=True),
        sa.Column('bio', sa.String(length=2000), nullable=True),
        sa.Column('links', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('user_id', sa.GUID(length=16), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['avatar_asset_id'],
            ['taas_media_assets.id'],
            name=op.f('fk_taas_blog_authors_avatar_asset_id_taas_media_assets'),
            ondelete='set null',
        ),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_authors_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_authors_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_authors')),
        sa.UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_authors_slug'),
    )
    with op.batch_alter_table('taas_blog_authors', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_authors_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_authors_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_blog_authors_blog_user',
            ['blog_id', 'user_id'],
            unique=True,
            postgresql_where=sa.text('user_id IS NOT NULL'),
        )

    op.create_table(
        'taas_blog_posts',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('subtitle', sa.String(length=300), nullable=True),
        sa.Column('excerpt', sa.String(length=1000), nullable=True),
        sa.Column('cover_asset_id', sa.GUID(length=16), nullable=True),
        sa.Column('cover_alt', sa.String(length=500), nullable=True),
        sa.Column('category_id', sa.GUID(length=16), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('featured', sa.Boolean(), nullable=False),
        sa.Column('seo', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('noindex', sa.Boolean(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('reading_minutes', sa.Integer(), nullable=False),
        sa.Column('draft_revision_id', sa.GUID(length=16), nullable=True),
        sa.Column('published_revision_id', sa.GUID(length=16), nullable=True),
        sa.Column('published_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('published_by', sa.GUID(length=16), nullable=True),
        sa.Column('scheduled_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('schedule_timezone', sa.String(length=64), nullable=True),
        sa.Column('submitted_by', sa.GUID(length=16), nullable=True),
        sa.Column('submitted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('review_comment', sa.String(length=2000), nullable=True),
        sa.Column('reviewed_by', sa.GUID(length=16), nullable=True),
        sa.Column('reviewed_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('locked_by', sa.GUID(length=16), nullable=True),
        sa.Column('lock_expires_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        sa.Column('updated_by', sa.GUID(length=16), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('draft', 'in_review', 'scheduled', 'published', 'unpublished', 'archived')",
            name=op.f('ck_taas_blog_posts_status'),
        ),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_posts_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['category_id'],
            ['taas_blog_categories.id'],
            name=op.f('fk_taas_blog_posts_category_id_taas_blog_categories'),
            ondelete='set null',
        ),
        sa.ForeignKeyConstraint(
            ['cover_asset_id'],
            ['taas_media_assets.id'],
            name=op.f('fk_taas_blog_posts_cover_asset_id_taas_media_assets'),
            ondelete='set null',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_posts_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_posts')),
    )
    with op.batch_alter_table('taas_blog_posts', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_posts_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            'ix_taas_blog_posts_blog_status', ['blog_id', 'status'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_posts_category_id'), ['category_id'], unique=False
        )
        batch_op.create_index(
            'ix_taas_blog_posts_due',
            ['scheduled_at'],
            unique=False,
            postgresql_where=sa.text("status = 'scheduled' AND deleted_at IS NULL"),
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_posts_tenant_id'), ['tenant_id'], unique=False
        )
        batch_op.create_index(
            'ux_taas_blog_posts_blog_slug',
            ['blog_id', 'slug'],
            unique=True,
            postgresql_where=sa.text('deleted_at IS NULL'),
        )

    op.create_table(
        'taas_blog_post_authors',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('post_id', sa.GUID(length=16), nullable=False),
        sa.Column('author_id', sa.GUID(length=16), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['author_id'],
            ['taas_blog_authors.id'],
            name=op.f('fk_taas_blog_post_authors_author_id_taas_blog_authors'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['post_id'],
            ['taas_blog_posts.id'],
            name=op.f('fk_taas_blog_post_authors_post_id_taas_blog_posts'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_post_authors_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_post_authors')),
        sa.UniqueConstraint(
            'post_id', 'author_id', name='uq_taas_blog_post_authors_post_author'
        ),
    )
    with op.batch_alter_table('taas_blog_post_authors', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_authors_author_id'),
            ['author_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_authors_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_blog_post_revisions',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('blog_id', sa.GUID(length=16), nullable=False),
        sa.Column('post_id', sa.GUID(length=16), nullable=False),
        sa.Column('doc', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.GUID(length=16), nullable=True),
        sa.Column('created_at', sa.DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['blog_id'],
            ['taas_blog_blogs.id'],
            name=op.f('fk_taas_blog_post_revisions_blog_id_taas_blog_blogs'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['post_id'],
            ['taas_blog_posts.id'],
            name=op.f('fk_taas_blog_post_revisions_post_id_taas_blog_posts'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_post_revisions_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_post_revisions')),
    )
    with op.batch_alter_table('taas_blog_post_revisions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_revisions_blog_id'), ['blog_id'], unique=False
        )
        batch_op.create_index(
            'ix_taas_blog_post_revisions_post', ['post_id', 'created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_revisions_tenant_id'),
            ['tenant_id'],
            unique=False,
        )

    op.create_table(
        'taas_blog_post_tags',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('tenant_id', sa.GUID(length=16), nullable=False),
        sa.Column('post_id', sa.GUID(length=16), nullable=False),
        sa.Column('tag_id', sa.GUID(length=16), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['post_id'],
            ['taas_blog_posts.id'],
            name=op.f('fk_taas_blog_post_tags_post_id_taas_blog_posts'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tag_id'],
            ['taas_blog_tags.id'],
            name=op.f('fk_taas_blog_post_tags_tag_id_taas_blog_tags'),
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=op.f('fk_taas_blog_post_tags_tenant_id_taas_tenants'),
            ondelete='cascade',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_taas_blog_post_tags')),
        sa.UniqueConstraint(
            'post_id', 'tag_id', name='uq_taas_blog_post_tags_post_tag'
        ),
    )
    with op.batch_alter_table('taas_blog_post_tags', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_tags_tag_id'), ['tag_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_taas_blog_post_tags_tenant_id'), ['tenant_id'], unique=False
        )


def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('taas_blog_post_tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_tags_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_tags_tag_id'))

    op.drop_table('taas_blog_post_tags')
    with op.batch_alter_table('taas_blog_post_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_revisions_tenant_id'))
        batch_op.drop_index('ix_taas_blog_post_revisions_post')
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_revisions_blog_id'))

    op.drop_table('taas_blog_post_revisions')
    with op.batch_alter_table('taas_blog_post_authors', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_authors_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_post_authors_author_id'))

    op.drop_table('taas_blog_post_authors')
    with op.batch_alter_table('taas_blog_posts', schema=None) as batch_op:
        batch_op.drop_index(
            'ux_taas_blog_posts_blog_slug',
            postgresql_where=sa.text('deleted_at IS NULL'),
        )
        batch_op.drop_index(batch_op.f('ix_taas_blog_posts_tenant_id'))
        batch_op.drop_index(
            'ix_taas_blog_posts_due',
            postgresql_where=sa.text("status = 'scheduled' AND deleted_at IS NULL"),
        )
        batch_op.drop_index(batch_op.f('ix_taas_blog_posts_category_id'))
        batch_op.drop_index('ix_taas_blog_posts_blog_status')
        batch_op.drop_index(batch_op.f('ix_taas_blog_posts_blog_id'))

    op.drop_table('taas_blog_posts')
    with op.batch_alter_table('taas_blog_authors', schema=None) as batch_op:
        batch_op.drop_index(
            'ux_taas_blog_authors_blog_user',
            postgresql_where=sa.text('user_id IS NOT NULL'),
        )
        batch_op.drop_index(batch_op.f('ix_taas_blog_authors_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_authors_blog_id'))

    op.drop_table('taas_blog_authors')
    with op.batch_alter_table('taas_blog_tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_tags_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_tags_blog_id'))

    op.drop_table('taas_blog_tags')
    with op.batch_alter_table('taas_blog_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_taas_blog_categories_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_categories_blog_id'))

    op.drop_table('taas_blog_categories')
    with op.batch_alter_table('taas_blog_blogs', schema=None) as batch_op:
        batch_op.drop_index(
            'ux_taas_blog_blogs_org_slug',
            postgresql_where=sa.text('deleted_at IS NULL'),
        )
        batch_op.drop_index(batch_op.f('ix_taas_blog_blogs_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_taas_blog_blogs_organization_id'))

    op.drop_table('taas_blog_blogs')


def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""


def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
