"""Site builder (app ``sites``): sites, page tree, immutable page revisions, releases, menus, redirects,
form submissions, audit and AI usage. Media comes from the media library (``taas_media_assets``).

System routes (``<org-slug>.<SITES_DOMAIN>/<site-slug>``) are derived from the organization and site
slugs; custom domains (``taas_site_domains``) arrive in P2. Spec: taas-specs/site-builder/.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from advanced_alchemy.base import UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import JSONB, SoftDeleteColumns
from db.models.core.constants import ORGANIZATION_TABLE, TENANT_TABLE

from .constants import (
    SITE_AI_USAGE_TABLE,
    SITE_AUDIT_TABLE,
    SITE_FORM_SUBMISSIONS_TABLE,
    SITE_MENUS_TABLE,
    SITE_PAGE_REVISIONS_TABLE,
    SITE_PAGES_TABLE,
    SITE_REDIRECTS_TABLE,
    SITE_RELEASES_TABLE,
    SITE_SITES_TABLE,
)


def _tenant_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{TENANT_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


def _site_fk() -> Mapped[UUID]:
    return mapped_column(
        GUID(length=16), ForeignKey(f'{SITE_SITES_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )


class Site(UUIDv7AuditBase, SoftDeleteColumns):
    """A website of an organization (RBAC domain ``site:<id>``)."""

    __tablename__ = SITE_SITES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_site_sites_org_slug',
            'organization_id',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
        Index(
            'ux_taas_site_sites_org_root',
            'organization_id',
            unique=True,
            postgresql_where=text('is_root AND deleted_at IS NULL'),
        ),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    organization_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{ORGANIZATION_TABLE}.id', ondelete='cascade'), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='draft', index=True)
    """``draft`` · ``published`` · ``archived``."""
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Served at ``<org>.<SITES_DOMAIN>/`` (one per organization)."""
    default_locale: Mapped[str] = mapped_column(String(16), nullable=False, default='en')
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    home_page_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    not_found_page_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    theme: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Design tokens + global ``header`` / ``footer`` sections (Site-0101, Site-0400)."""
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """SEO defaults, AI brand voice, form notification e-mail, …"""
    live_release_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    preview_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Bumped to revoke every preview link of the site (Site-0505)."""
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)


class SitePage(UUIDv7AuditBase, SoftDeleteColumns):
    """A page of the site tree; content lives in revisions (``draft_revision_id`` / ``published_revision_id``)."""

    __tablename__ = SITE_PAGES_TABLE
    __table_args__ = (
        Index(
            'ux_taas_site_pages_site_path',
            'site_id',
            'locale',
            'path',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
        Index('ix_taas_site_pages_site_parent', 'site_id', 'parent_id', 'position'),
    )

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    parent_id: Mapped[UUID | None] = mapped_column(
        GUID(length=16), ForeignKey(f'{SITE_PAGES_TABLE}.id', ondelete='cascade'), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    """``/`` for the home page, else ``/<parent-slugs>/<slug>``."""
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default='en')
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='page')
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_menu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    noindex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """``title``, ``description``, ``canonical``, ``og_image`` (``asset:<id>``)."""
    draft_revision_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    published_revision_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    """Revision in the live release (``None`` = never published)."""
    locked_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class SitePageRevision(UUIDv7Base):
    """Immutable JSON document of a page (Site-0103); the latest autosave is the draft."""

    __tablename__ = SITE_PAGE_REVISIONS_TABLE
    __table_args__ = (Index('ix_taas_site_page_revisions_page', 'page_id', 'created_at'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    page_id: Mapped[UUID] = mapped_column(
        GUID(length=16), ForeignKey(f'{SITE_PAGES_TABLE}.id', ondelete='cascade'), nullable=False
    )
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='visual')
    """``visual`` · ``markdown`` · ``ai`` · ``import`` · ``template`` · ``restore``."""
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    seo: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    author_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)


class SiteRelease(UUIDv7Base):
    """A published, self-contained snapshot of the whole site (pages, theme, menus, redirects)."""

    __tablename__ = SITE_RELEASES_TABLE
    __table_args__ = (UniqueConstraint('site_id', 'number', name='uq_taas_site_releases_number'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    """Pages added / changed / removed against the previous release."""
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)
    rollback_of: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)


class SiteMenu(UUIDv7AuditBase):
    """Header / footer navigation (Site-0102): items link to pages (follow renames), URLs or anchors."""

    __tablename__ = SITE_MENUS_TABLE
    __table_args__ = (UniqueConstraint('site_id', 'key', name='uq_taas_site_menus_key'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    items: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class SiteRedirect(UUIDv7AuditBase):
    """Per-site redirect, evaluated before page lookup (Site-0613); created on slug changes (Site-0603)."""

    __tablename__ = SITE_REDIRECTS_TABLE
    __table_args__ = (UniqueConstraint('site_id', 'from_path', name='uq_taas_site_redirects_from'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    from_path: Mapped[str] = mapped_column(String(512), nullable=False)
    to: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=301)
    auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SiteFormSubmission(UUIDv7Base):
    """A visitor's submission of a form block (``form_key`` = block id)."""

    __tablename__ = SITE_FORM_SUBMISSIONS_TABLE
    __table_args__ = (Index('ix_taas_site_form_submissions_site', 'site_id', 'created_at'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID] = _site_fk()
    page_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    form_key: Mapped[str] = mapped_column(String(64), nullable=False)
    form_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spam_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)


class SiteAudit(UUIDv7Base):
    """Every change of a site (Site-0003): who, what, when, source; AI requests (Site-0815)."""

    __tablename__ = SITE_AUDIT_TABLE
    __table_args__ = (Index('ix_taas_site_audit_site', 'site_id', 'created_at'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    site_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    actor_id: Mapped[UUID | None] = mapped_column(GUID(length=16), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), nullable=False)


class SiteAiUsage(UUIDv7AuditBase):
    """AI credits used by a tenant per month (Site-0811)."""

    __tablename__ = SITE_AI_USAGE_TABLE
    __table_args__ = (UniqueConstraint('tenant_id', 'period', name='uq_taas_site_ai_usage_period'),)

    tenant_id: Mapped[UUID] = _tenant_fk()
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    """``YYYY-MM``."""
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
