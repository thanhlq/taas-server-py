"""Wire types of ``/api/v1/sites`` (msgspec, snake_case JSON). Documents / themes / menus are JSON
objects validated by ``_document`` / ``_rules``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec
from foundation.serialization import ApiRequest, ApiResponse

# Members: the shared shapes of every object app (one OpenAPI component each), re-exported for the site routes.
from ews.access.schemas import CandidateOut as CandidateOut
from ews.access.schemas import MemberOut as MemberOut
from ews.access.schemas import MemberUpsert as MemberUpsert
from ews.access.schemas import RoleOut as RoleOut

# --- access ---------------------------------------------------------------------------------------


class SitesAccessOut(ApiResponse, kw_only=True):
    allowed: bool
    """The caller can open the app (an organization right or a role on one of its sites)."""
    can_create: bool
    sites_domain: str
    organization_slug: str


# --- sites ----------------------------------------------------------------------------------------


class SiteOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str
    description: str | None = None
    status: str
    is_root: bool = False
    default_locale: str = 'en'
    template: str | None = None
    url: str
    """Public URL of the site (system host)."""
    home_page_id: str | None = None
    not_found_page_id: str | None = None
    theme: dict[str, Any] = msgspec.field(default_factory=dict)
    settings: dict[str, Any] = msgspec.field(default_factory=dict)
    live_release_id: str | None = None
    live_release_number: int | None = None
    published_at: datetime | None = None
    page_count: int = 0
    pending_changes: int = 0
    role: str | None = None
    """The caller's role on the site (``None`` = through an organization role)."""
    permissions: list[str] = msgspec.field(default_factory=list)
    """``sites.*`` permissions of the caller on this site, e.g. ``sites.page:publish``."""
    created_at: datetime
    updated_at: datetime


class SiteCreate(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None
    description: str | None = None
    template: str = 'blank'
    is_root: bool = False


class SiteUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    is_root: bool | None = None
    default_locale: str | None = None
    settings: dict[str, Any] | None = None
    home_page_id: str | None = None
    not_found_page_id: str | None = None


class ThemeUpdate(ApiRequest, kw_only=True):
    theme: dict[str, Any]


class ThemeOut(ApiResponse, kw_only=True):
    theme: dict[str, Any]
    issues: list[dict[str, Any]] = msgspec.field(default_factory=list)


class TemplateOut(ApiResponse, kw_only=True):
    key: str
    name: str
    description: str
    colors: dict[str, str]
    fonts: dict[str, str]
    pages: list[str]


# --- pages ----------------------------------------------------------------------------------------


class PageOut(ApiResponse, kw_only=True):
    id: str
    site_id: str
    parent_id: str | None = None
    slug: str
    path: str
    title: str
    position: int = 0
    in_menu: bool = True
    noindex: bool = False
    is_home: bool = False
    is_not_found: bool = False
    seo: dict[str, Any] = msgspec.field(default_factory=dict)
    status: Literal['draft', 'published', 'changed']
    """``draft`` never published · ``published`` live = draft · ``changed`` draft differs from live."""
    draft_revision_id: str | None = None
    published_revision_id: str | None = None
    locked_by: str | None = None
    locked_by_name: str | None = None
    locked_at: datetime | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PageDetailOut(PageOut, kw_only=True):
    doc: dict[str, Any]
    revision_created_at: datetime | None = None
    revision_source: str | None = None


class PageCreate(ApiRequest, kw_only=True):
    title: str
    slug: str | None = None
    parent_id: str | None = None
    in_menu: bool = True
    copy_of: str | None = None
    """Duplicate the draft of another page of the site."""
    doc: dict[str, Any] | None = None


class PageUpdate(ApiRequest, kw_only=True):
    title: str | None = None
    slug: str | None = None
    parent_id: str | None | msgspec.UnsetType = msgspec.UNSET
    position: int | None = None
    in_menu: bool | None = None
    noindex: bool | None = None
    seo: dict[str, Any] | None = None


class DraftSave(ApiRequest, kw_only=True):
    doc: dict[str, Any]
    source: Literal['visual', 'markdown', 'ai', 'import'] = 'visual'
    base_revision_id: str | None = None
    """The draft the editor loaded; a newer draft of another author → 409."""
    title: str | None = None
    seo: dict[str, Any] | None = None
    note: str | None = None


class DraftOut(ApiResponse, kw_only=True):
    revision_id: str
    created_at: datetime
    new_revision: bool


class RevisionOut(ApiResponse, kw_only=True):
    id: str
    source: str
    title: str
    author_id: str | None = None
    author_name: str | None = None
    note: str | None = None
    created_at: datetime
    is_draft: bool = False
    is_published: bool = False


class RevisionDetailOut(RevisionOut, kw_only=True):
    doc: dict[str, Any]


class LockRequest(ApiRequest, kw_only=True):
    force: bool = False


class LockOut(ApiResponse, kw_only=True):
    locked: bool
    """``True`` = the caller holds the lock."""
    holder_id: str | None = None
    holder_name: str | None = None
    locked_at: datetime | None = None


class DocumentIn(ApiRequest, kw_only=True):
    doc: dict[str, Any]


class ValidationOut(ApiResponse, kw_only=True):
    valid: bool
    issues: list[str]


# --- menus / redirects ----------------------------------------------------------------------------


class MenuOut(ApiResponse, kw_only=True):
    key: str
    items: list[dict[str, Any]]


class MenuUpdate(ApiRequest, kw_only=True):
    items: list[dict[str, Any]]


class RedirectOut(ApiResponse, kw_only=True):
    id: str
    from_path: str
    to: str
    status_code: int
    auto: bool
    created_at: datetime


class RedirectCreate(ApiRequest, kw_only=True):
    from_path: str
    to: str
    status_code: int = 301


# --- publishing -----------------------------------------------------------------------------------


class ChangeOut(ApiResponse, kw_only=True):
    kind: Literal['page_added', 'page_changed', 'page_removed', 'theme', 'menus', 'redirects', 'settings']
    page_id: str | None = None
    title: str | None = None
    path: str | None = None


class AccessibilityIssueOut(ApiResponse, kw_only=True):
    severity: str
    code: str
    message: str
    page_id: str | None = None
    page_title: str | None = None
    block_id: str | None = None


class ChangesOut(ApiResponse, kw_only=True):
    changes: list[ChangeOut]
    issues: list[AccessibilityIssueOut]


class PublishRequest(ApiRequest, kw_only=True):
    page_ids: list[str] | None = None
    """Partial publish: only these pages' drafts (theme / menus / redirects are always included)."""
    note: str | None = None
    ignore_accessibility: bool = False


class ReleaseOut(ApiResponse, kw_only=True):
    id: str
    number: int
    note: str | None = None
    changes: list[dict[str, Any]] = msgspec.field(default_factory=list)
    page_count: int = 0
    published_by: str | None = None
    published_by_name: str | None = None
    published_at: datetime
    is_live: bool = False
    rollback_of: str | None = None


class PreviewLinkRequest(ApiRequest, kw_only=True):
    page_id: str | None = None
    days: int = 7


class PreviewLinkOut(ApiResponse, kw_only=True):
    url: str
    expires_at: datetime


# --- forms ----------------------------------------------------------------------------------------


class SubmissionOut(ApiResponse, kw_only=True):
    id: str
    form_key: str
    form_title: str | None = None
    page_id: str | None = None
    page_title: str | None = None
    data: dict[str, Any]
    notified: bool = False
    created_at: datetime


class SubmissionPage(ApiResponse, kw_only=True):
    items: list[SubmissionOut]
    total: int


class FormSubmit(ApiRequest, kw_only=True):
    data: dict[str, Any]
    page_id: str | None = None
    ip_hash: str | None = None
    honeypot: str | None = None


class FormSubmitOut(ApiResponse, kw_only=True):
    ok: bool
    message: str | None = None
    redirect: str | None = None


# --- export / import / audit ----------------------------------------------------------------------


class SiteExportOut(ApiResponse, kw_only=True):
    format: str
    version: int
    site: dict[str, Any]
    theme: dict[str, Any]
    menus: dict[str, Any]
    pages: list[dict[str, Any]]
    redirects: list[dict[str, Any]]
    assets: list[dict[str, Any]]


class SiteImport(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None
    export: dict[str, Any]


class AuditOut(ApiResponse, kw_only=True):
    id: str
    action: str
    actor_id: str | None = None
    actor_name: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    source: str | None = None
    detail: dict[str, Any] = msgspec.field(default_factory=dict)
    created_at: datetime


# --- AI -------------------------------------------------------------------------------------------


class AiTextRequest(ApiRequest, kw_only=True):
    action: Literal['rewrite', 'shorten', 'expand', 'fix', 'tone', 'translate']
    text: str
    tone: str | None = None
    language: str | None = None
    page_id: str | None = None


class AiTextOut(ApiResponse, kw_only=True):
    request_id: str
    text: str
    model: str


class AiSectionRequest(ApiRequest, kw_only=True):
    prompt: str
    page_id: str | None = None


class AiSectionOut(ApiResponse, kw_only=True):
    request_id: str
    blocks: list[dict[str, Any]]
    model: str


class AiSeoRequest(ApiRequest, kw_only=True):
    page_id: str
    doc: dict[str, Any] | None = None


class AiSeoOut(ApiResponse, kw_only=True):
    request_id: str
    title: str
    description: str
    model: str


class AiAltRequest(ApiRequest, kw_only=True):
    asset_id: str


class AiAltOut(ApiResponse, kw_only=True):
    request_id: str
    alt: str
    model: str


class AiFeedback(ApiRequest, kw_only=True):
    request_id: str
    accepted: bool


class AiUsageOut(ApiResponse, kw_only=True):
    enabled: bool
    provider: str
    period: str
    used: int
    limit: int
    """Monthly token credits of the tenant (0 = unlimited)."""


# --- internal (renderer) --------------------------------------------------------------------------


class RouteOut(ApiResponse, kw_only=True):
    host: str
    prefix: str
    site_id: str | None = None
    """Set on ``site`` routes."""
    blog_id: str | None = None
    """Set on ``blog`` routes (release = ``GET /blog-releases/{release_id}``)."""
    tenant_id: str
    release_id: str | None = None
    kind: Literal['site', 'redirect', 'blog'] = 'site'
    redirect_to: str | None = None
    redirect_status: int | None = None
    """``redirect`` routes: 301 · 302 · 307 · 308 (the renderer defaults to 308)."""


class RoutesOut(ApiResponse, kw_only=True):
    version: str
    sites_domain: str
    routes: list[RouteOut]


class SnapshotOut(ApiResponse, kw_only=True):
    release_id: str | None = None
    snapshot: dict[str, Any]
