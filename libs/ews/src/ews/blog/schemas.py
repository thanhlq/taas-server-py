"""Wire types of ``/api/v1/blog`` (msgspec, snake_case JSON), prefixed ``Blog`` (OpenAPI component names are global). Post bodies are site documents
``{schemaVersion, sections}`` validated by ``ews.sites`` (Blog-0100). Members / roles: ``ews.access.schemas``.

``omit_defaults``: ``false``, ``0``, ``[]`` and ``null`` are left out of responses — clients default them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec
from foundation.serialization import ApiRequest, ApiResponse

from ews.sites.schemas import DocumentIn, ValidationOut  # noqa: F401 (same wire types as the Site Builder)

PostStatus = Literal[
    'draft', 'in_review', 'scheduled', 'published', 'unpublished', 'archived'
]
RevisionSource = Literal['visual', 'markdown', 'ai', 'import']

# --- access / blogs ---------------------------------------------------------------------------------


class BlogAccessOut(ApiResponse, kw_only=True):
    allowed: bool
    """The caller can open the app: an organization-level ``blog.*`` right or a role on one of its blogs."""
    can_create: bool
    organization_slug: str


class BlogOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    public_url: str
    """Public address of the blog home: ``<scheme>://<org>.<SITES_DOMAIN>[:port]/<slug>/`` (Blog-0110)."""
    name: str
    description: str | None = None
    locale: str = 'en'
    mount: Literal['system', 'site'] = 'system'
    status: Literal['active', 'archived'] = 'active'
    settings: dict[str, Any] = msgspec.field(default_factory=dict)
    """Every setting with its default filled in (``posts_per_page``, ``default_author_id``, ``feed_enabled``,
    ``feed_full_text``, ``ai_voice``)."""
    post_count: int = 0
    role: str | None = None
    """The caller's role on the blog (``None`` = through an organization role)."""
    permissions: list[str] = msgspec.field(default_factory=list)
    """``blog.*`` permissions of the caller on this blog (detail only), e.g. ``blog.post:publish``."""
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class BlogCreate(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None
    description: str | None = None
    locale: str = 'en'
    settings: dict[str, Any] | None = None


class BlogUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    slug: str | None = None
    description: str | None | msgspec.UnsetType = msgspec.UNSET
    locale: str | None = None
    mount: Literal['system', 'site'] | None = None
    settings: dict[str, Any] | None = None
    """Merged into the current settings; a ``null`` value resets that key."""
    status: Literal['active', 'archived'] | None = None


# --- taxonomy & authors -----------------------------------------------------------------------------


class BlogTermRef(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str


class BlogAuthorRef(ApiResponse, kw_only=True):
    id: str
    slug: str
    display_name: str
    avatar_asset_id: str | None = None
    user_id: str | None = None


class BlogCategoryOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str
    description: str | None = None
    position: int = 0
    seo: dict[str, Any] = msgspec.field(default_factory=dict)
    post_count: int = 0


class BlogCategoryCreate(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None
    description: str | None = None
    seo: dict[str, Any] | None = None


class BlogCategoryUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    slug: str | None = None
    description: str | None | msgspec.UnsetType = msgspec.UNSET
    position: int | None = None
    """New index in the ordered list (others shift)."""
    seo: dict[str, Any] | None = None


class BlogTagOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str
    post_count: int = 0


class BlogTagCreate(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None


class BlogTagUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    slug: str | None = None


class BlogAuthorOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    display_name: str
    avatar_asset_id: str | None = None
    bio: str | None = None
    links: list[dict[str, str]] = msgspec.field(default_factory=list)
    user_id: str | None = None
    """Linked TaaS user (``None`` = guest author without an account)."""
    post_count: int = 0


class BlogAuthorCreate(ApiRequest, kw_only=True):
    display_name: str
    slug: str | None = None
    avatar_asset_id: str | None = None
    bio: str | None = None
    links: list[dict[str, str]] | None = None
    user_id: str | None = None


class BlogAuthorUpdate(ApiRequest, kw_only=True):
    display_name: str | None = None
    slug: str | None = None
    avatar_asset_id: str | None | msgspec.UnsetType = msgspec.UNSET
    bio: str | None | msgspec.UnsetType = msgspec.UNSET
    links: list[dict[str, str]] | None = None
    user_id: str | None | msgspec.UnsetType = msgspec.UNSET


# --- posts ------------------------------------------------------------------------------------------


class BlogPostOut(ApiResponse, kw_only=True):
    id: str
    blog_id: str
    slug: str
    slug_auto: bool = False
    """The slug follows the title: never published and not edited by hand (Blog-0107)."""
    former_slugs: list[str] = msgspec.field(default_factory=list)
    """Earlier addresses (changed after the first publication, oldest first) → 301 to ``slug`` (Blog-0108)."""
    public_url: str
    """Public address: the blog's ``public_url`` + ``slug`` (Blog-0110), also before publication."""
    live: bool = False
    """Readable on the public blog now: published and the blog is active."""
    title: str
    subtitle: str | None = None
    excerpt: str | None = None
    status: PostStatus
    has_changes: bool = False
    """Published post whose draft differs from the live revision (publish again = **Update**)."""
    cover_asset_id: str | None = None
    cover_alt: str | None = None
    category: BlogTermRef | None = None
    tags: list[BlogTermRef] = msgspec.field(default_factory=list)
    authors: list[BlogAuthorRef] = msgspec.field(default_factory=list)
    featured: bool = False
    word_count: int = 0
    reading_minutes: int = 0
    published_at: datetime | None = None
    scheduled_at: datetime | None = None
    schedule_timezone: str | None = None
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    submitted_at: datetime | None = None
    draft_revision_id: str | None = None
    published_revision_id: str | None = None
    locked_by: str | None = None
    locked_by_name: str | None = None
    lock_expires_at: datetime | None = None
    can_edit: bool = False
    """The caller may edit this post (``update``, or ``update_own`` on an own post)."""
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class BlogPostDetailOut(BlogPostOut, kw_only=True):
    seo: dict[str, Any] = msgspec.field(default_factory=dict)
    noindex: bool = False
    doc: dict[str, Any]
    """Draft body (site document)."""
    revision_created_at: datetime | None = None
    revision_source: str | None = None
    permissions: list[str] = msgspec.field(default_factory=list)
    """``blog.*`` permissions of the caller on the post's blog."""


class BlogPostListOut(ApiResponse, kw_only=True):
    items: list[BlogPostOut]
    total: int
    counts: dict[str, int]
    """Posts per status for the quick tabs, with the other filters applied; ``all`` = every status but
    ``archived``."""


class BlogPostCreate(ApiRequest, kw_only=True):
    title: str = ''
    """Empty → ``Untitled``."""
    slug: str | None = None
    doc: dict[str, Any] | None = None
    source: RevisionSource = 'visual'
    category_id: str | None = None
    tag_ids: list[str] | None = None
    author_ids: list[str] | None = None
    """Ordered byline; default: the caller's author profile (created on first use)."""
    featured: bool = False


class BlogPostUpdate(ApiRequest, kw_only=True):
    title: str | None = None
    subtitle: str | None | msgspec.UnsetType = msgspec.UNSET
    excerpt: str | None | msgspec.UnsetType = msgspec.UNSET
    slug: str | None = None
    """A new slug (``slug_auto`` off; 409 ``slug_taken``, 400 reserved) · ``""`` = from the title again (Blog-0107)."""
    cover_asset_id: str | None | msgspec.UnsetType = msgspec.UNSET
    cover_alt: str | None | msgspec.UnsetType = msgspec.UNSET
    category_id: str | None | msgspec.UnsetType = msgspec.UNSET
    tag_ids: list[str] | None = None
    author_ids: list[str] | None = None
    featured: bool | None = None
    seo: dict[str, Any] | None = None
    """``title``, ``description``, ``canonical``, ``og_image`` (``asset:<id>``) — replaces the SEO object."""
    noindex: bool | None = None


class BlogDraftSave(ApiRequest, kw_only=True):
    doc: dict[str, Any]
    title: str | None = None
    source: RevisionSource = 'visual'
    base_revision_id: str | None = None
    """Revision the editor started from: 409 ``stale_draft`` when another user saved since."""
    note: str | None = None
    """A note forces a new revision (named version)."""


class BlogDraftOut(ApiResponse, kw_only=True):
    revision_id: str
    created_at: datetime
    new_revision: bool
    word_count: int = 0
    reading_minutes: int = 0
    slug: str
    """The address after the save: it follows the title while ``slug_auto`` (Blog-0107)."""
    slug_auto: bool = False
    public_url: str


class BlogRevisionOut(ApiResponse, kw_only=True):
    id: str
    source: str
    title: str
    created_by: str | None = None
    created_by_name: str | None = None
    note: str | None = None
    created_at: datetime
    is_draft: bool = False
    is_published: bool = False


class BlogRevisionDetailOut(BlogRevisionOut, kw_only=True):
    doc: dict[str, Any]
    meta: dict[str, Any] = msgspec.field(default_factory=dict)


class BlogLockRequest(ApiRequest, kw_only=True):
    force: bool = False
    """Take the lock over from another user (after confirmation)."""


class BlogLockOut(ApiResponse, kw_only=True):
    locked: bool
    """``True`` = the caller holds the lock."""
    holder_id: str | None = None
    holder_name: str | None = None
    expires_at: datetime | None = None


# --- workflow ---------------------------------------------------------------------------------------


class BlogCommentIn(ApiRequest, kw_only=True):
    comment: str


class BlogScheduleIn(ApiRequest, kw_only=True):
    scheduled_at: datetime
    """Without an offset: wall time in ``timezone``."""
    timezone: str = 'UTC'
    """IANA zone, e.g. ``Europe/Paris``."""


class BlogApproveIn(ApiRequest, kw_only=True):
    scheduled_at: datetime | None = None
    """Set → approve and schedule; else approve and publish now."""
    timezone: str | None = None


# --- renderer (``/api/v1/sites-internal``, blog-publishing-spec §5) --------------------------------------


class BlogReleaseSnapshotOut(ApiResponse, kw_only=True):
    release_id: str
    snapshot: dict[str, Any]
    """``BlogSnapshot`` (blog-publishing-spec §5) — immutable: cache forever."""


class BlogPublishedBodyOut(ApiResponse, kw_only=True):
    revision_id: str
    doc: dict[str, Any]
    """Body of a published revision (site document)."""
    assets: dict[str, Any]
    """Media of the body + cover: ``{assetId: SnapshotAsset}`` with ``public`` CDN URLs when a CDN is set."""
    cdn_origin: str | None
