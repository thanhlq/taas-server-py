"""Blog (app ``blog``): blogs of an organization, posts with immutable revisions (body = the site document
``{schemaVersion, sections}`` of the Site Builder), categories, tags and author profiles.

RBAC domain of a blog: ``blog:<id>`` (roles ``blog_admin`` · ``blog_editor`` · ``blog_author`` ·
``blog_viewer``). Covers and avatars are media library assets (``taas_media_assets``). Public reading: immutable
releases (``taas_blog_releases``, the index read by the site renderer) + the published revisions (bodies).
Specs: taas-specs/blog/blog-app-spec.md §3, blog-publishing-spec.md §3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE
from db.models.media.constants import MEDIA_ASSETS_TABLE

from .constants import (
    BLOG_AUTHORS_TABLE,
    BLOG_BLOGS_TABLE,
    BLOG_CATEGORIES_TABLE,
    BLOG_POST_AUTHORS_TABLE,
    BLOG_POST_REVISIONS_TABLE,
    BLOG_POST_TAGS_TABLE,
    BLOG_POSTS_TABLE,
    BLOG_RELEASES_TABLE,
    BLOG_TAGS_TABLE,
)

POST_STATUSES = (
    'draft',
    'in_review',
    'scheduled',
    'published',
    'unpublished',
    'archived',
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _blog_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{BLOG_BLOGS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


def _post_fk() -> Mapped[UUID]:
    """Not indexed alone: each child table leads a composite index / unique constraint with ``post_id``."""
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{BLOG_POSTS_TABLE}.id', ondelete='cascade'),
        nullable=False,
    )


def _asset_fk() -> Mapped[UUID | None]:
    return mapped_column(
        GUID(length=16),
        ForeignKey(f'{MEDIA_ASSETS_TABLE}.id', ondelete='set null'),
        nullable=True,
    )


class Blog(UUIDv7AuditBase, SoftDeleteColumns):
    """A blog of an organization (RBAC domain ``blog:<id>``)."""

    __tablename__ = BLOG_BLOGS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_blog_blogs_org_slug',
            'organization_id',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
        CheckConstraint("mount in ('system', 'site')", name='mount'),
        CheckConstraint("status in ('active', 'archived')", name='status'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default='en')
    mount: Mapped[str] = mapped_column(String(16), nullable=False, default='system')
    """``system`` → ``<org>.<SITES_DOMAIN>/<slug>`` · ``site`` → mounted on a site path (B3)."""
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    """Posts per page, default author, feeds, AI voice (``ews.blog._rules.clean_settings``)."""
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    """``active`` · ``archived`` (read-only)."""
    live_release_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """The release the site renderer serves (``taas_blog_releases``); rebuilt on every public change."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class BlogRelease(UUIDv7Base):
    """An immutable snapshot of a blog's public index (posts, taxonomy, authors, media) — blog-publishing-spec §5.
    The last 20 per blog are kept."""

    __tablename__ = BLOG_RELEASES_TABLE
    __table_args__ = (
        UniqueConstraint('blog_id', 'version', name='uq_taas_blog_releases_version'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )


class BlogCategory(UUIDv7AuditBase):
    """A category of a blog (flat, ordered by ``position``)."""

    __tablename__ = BLOG_CATEGORIES_TABLE
    __table_args__ = (
        UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_categories_slug'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class BlogTag(UUIDv7AuditBase):
    __tablename__ = BLOG_TAGS_TABLE
    __table_args__ = (
        UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_tags_slug'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class BlogAuthor(UUIDv7AuditBase):
    """An author profile of a blog: a user of the organization (``user_id``) or a guest without an account."""

    __tablename__ = BLOG_AUTHORS_TABLE
    __table_args__ = (
        UniqueConstraint('blog_id', 'slug', name='uq_taas_blog_authors_slug'),
        Index(
            'ux_taas_blog_authors_blog_user',
            'blog_id',
            'user_id',
            unique=True,
            postgresql_where=text('user_id IS NOT NULL'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar_asset_id: Mapped[UUID | None] = _asset_fk()
    bio: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    links: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    """``[{label, url}]`` (http(s) / mailto)."""
    user_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class BlogPost(UUIDv7AuditBase, SoftDeleteColumns):
    """A post; its body lives in revisions (``draft_revision_id`` = working copy, ``published_revision_id`` =
    live). Statuses: ``draft`` → ``in_review`` → ``scheduled`` → ``published`` → ``unpublished`` · ``archived``."""

    __tablename__ = BLOG_POSTS_TABLE
    __table_args__ = (
        Index(
            'ux_taas_blog_posts_blog_slug',
            'blog_id',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
        Index('ix_taas_blog_posts_blog_status', 'blog_id', 'status'),
        Index(
            'ix_taas_blog_posts_due',
            'scheduled_at',
            postgresql_where=text("status = 'scheduled' AND deleted_at IS NULL"),
        ),
        CheckConstraint(
            "status in ('draft', 'in_review', 'scheduled', 'published', 'unpublished', 'archived')",
            name='status',
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    slug_auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text('true')
    )
    """The slug follows the title (Blog-0107) while the post was never published and nobody edited it."""
    former_slugs: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    """Slugs of the post before a change after its first publication (≤ 20) → public 301 (Blog-0108)."""
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cover_asset_id: Mapped[UUID | None] = _asset_fk()
    cover_alt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{BLOG_CATEGORIES_TABLE}.id', ondelete='set null'),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='draft')
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """``title``, ``description``, ``canonical``, ``og_image`` (``asset:<id>``)."""
    noindex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reading_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Of the draft body (``ews.blog._rules.reading_time``)."""
    draft_revision_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    published_revision_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), nullable=True
    )
    """Live revision (``None`` = not on the public blog)."""
    published_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    """First publication (kept by later updates and by unpublish)."""
    published_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    schedule_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """IANA zone the editor scheduled in (display only; ``scheduled_at`` is UTC)."""
    submitted_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    """Last "request changes" comment of an editor."""
    reviewed_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    locked_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class BlogPostRevision(UUIDv7Base):
    """Body + metadata snapshot of a post. The working draft is updated in place by autosaves of the same user;
    a published revision never changes."""

    __tablename__ = BLOG_POST_REVISIONS_TABLE
    __table_args__ = (
        Index('ix_taas_blog_post_revisions_post', 'post_id', 'created_at'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    blog_id: Mapped[UUID] = _blog_fk()
    post_id: Mapped[UUID] = _post_fk()
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='visual')
    """``visual`` · ``markdown`` · ``ai`` · ``import`` · ``restore``."""
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Metadata at save / publish time: slug, subtitle, excerpt, cover, category, tags, authors, SEO."""
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assets: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """Set when the revision goes live: media of the body + cover with their CDN URLs (``asset_map`` shape)."""
    cdn_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Origin of ``assets[*].public`` (``None`` without a public store)."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTimeUTC(timezone=True), nullable=False
    )


class BlogPostTag(UUIDv7Base):
    __tablename__ = BLOG_POST_TAGS_TABLE
    __table_args__ = (
        UniqueConstraint('post_id', 'tag_id', name='uq_taas_blog_post_tags_post_tag'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    post_id: Mapped[UUID] = _post_fk()
    tag_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{BLOG_TAGS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )


class BlogPostAuthor(UUIDv7Base):
    """Byline of a post, ordered by ``position``."""

    __tablename__ = BLOG_POST_AUTHORS_TABLE
    __table_args__ = (
        UniqueConstraint(
            'post_id', 'author_id', name='uq_taas_blog_post_authors_post_author'
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    post_id: Mapped[UUID] = _post_fk()
    author_id: Mapped[UUID] = mapped_column(
        GUID(length=16),
        ForeignKey(f'{BLOG_AUTHORS_TABLE}.id', ondelete='cascade'),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
