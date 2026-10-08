"""Wire types of ``/api/v1/knowledge`` (msgspec, snake_case JSON). Page bodies are site documents (``_document``).
Members routes use ``ews.access`` (``MemberOut``, ``MemberUpsert``, ``CandidateOut``, ``RoleOut``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec
from foundation.serialization import ApiRequest, ApiResponse

Visibility = Literal['tenant', 'organization', 'restricted']
PageStatus = Literal['draft', 'published', 'changed']
ReviewStatus = Literal['verified', 'due', 'expired', 'unverified']

# --- app ------------------------------------------------------------------------------------------


class KnowledgeAccessOut(ApiResponse, kw_only=True):
    allowed: bool
    """Every signed-in member of the organization may open the app."""
    can_create_space: bool
    """``kb.space:create`` on the organization chain (org admin) or the tenant (``kb_admin``)."""
    organization_slug: str


class KbTemplateOut(ApiResponse, kw_only=True):
    key: str
    name: str
    description: str
    icon: str
    title: str
    """Default title of a page made from the template."""
    doc: dict[str, Any]


# --- spaces ---------------------------------------------------------------------------------------


class KbSpaceOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    visibility: Visibility
    include_sub_orgs: bool
    organization_id: str
    organization_name: str
    organization_slug: str
    page_count: int
    """Published pages."""
    role: str | None = None
    """The caller's role: a member role, else ``kb_space_viewer`` from the visibility; ``None`` = through an
    organization / tenant role (admins)."""
    permissions: list[str] = msgspec.field(default_factory=list)
    """``kb.*`` permissions of the caller on the space (UI hints), e.g. ``kb.page:publish``."""
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class KbSpaceRefOut(ApiResponse, kw_only=True):
    id: str
    slug: str
    name: str
    icon: str | None = None
    color: str | None = None
    visibility: Visibility


class KbSpaceCreate(ApiRequest, kw_only=True):
    name: str
    slug: str | None = None
    """Unique in the tenant; default: from the name."""
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    visibility: Visibility = 'organization'
    include_sub_orgs: bool = False


class KbSpaceUpdate(ApiRequest, kw_only=True):
    name: str | None = None
    slug: str | None = None
    description: str | None | msgspec.UnsetType = msgspec.UNSET
    icon: str | None | msgspec.UnsetType = msgspec.UNSET
    color: str | None | msgspec.UnsetType = msgspec.UNSET
    visibility: Visibility | None = None
    include_sub_orgs: bool | None = None


# --- pages ----------------------------------------------------------------------------------------


class KbLockOut(ApiResponse, kw_only=True):
    locked: bool
    """``True`` = the caller holds the lock."""
    holder_id: str | None = None
    holder_name: str | None = None
    locked_until: datetime | None = None


class KbPageOut(ApiResponse, kw_only=True):
    id: str
    space_id: str
    parent_id: str | None
    """``null`` = top level."""
    title: str
    """Draft title for editors, published title for readers."""
    slug: str
    position: int
    depth: int
    status: PageStatus
    owner_id: str | None = None
    owner_name: str | None = None
    review_interval_days: int | None = None
    verified_at: datetime | None = None
    verified_until: datetime | None = None
    review_status: ReviewStatus
    published_at: datetime | None = None
    lock: KbLockOut | None = None
    """Editors only: the soft lock while someone edits (``None`` = free)."""
    created_at: datetime
    updated_at: datetime


class KbBreadcrumbOut(ApiResponse, kw_only=True):
    id: str
    title: str


class KbPageDetailOut(KbPageOut, kw_only=True):
    view: Literal['draft', 'published']
    """Editors read the draft (``?view=published`` for the live version), readers the published version."""
    doc: dict[str, Any]
    revision_id: str | None = None
    version: int | None = None
    """Published version number of the shown revision (``None`` = draft)."""
    draft_revision_id: str | None = None
    published_revision_id: str | None = None
    permissions: list[str] = msgspec.field(default_factory=list)
    breadcrumbs: list[KbBreadcrumbOut] = msgspec.field(default_factory=list)
    space: KbSpaceRefOut


class KbPageCreate(ApiRequest, kw_only=True):
    title: str | None = None
    """Default: the template's title, else ``Untitled``."""
    parent_id: str | None = None
    position: int | None = None
    """Among the siblings (default: last)."""
    template: str | None = None
    """Key of ``GET /knowledge/templates``."""
    doc: dict[str, Any] | None = None
    review_interval_days: int | None | msgspec.UnsetType = msgspec.UNSET
    """Default 180; ``null`` = no periodic review."""


class KbPageUpdate(ApiRequest, kw_only=True):
    slug: str | None = None
    owner_id: str | None = None
    review_interval_days: int | None | msgspec.UnsetType = msgspec.UNSET


class KbPageMove(ApiRequest, kw_only=True):
    parent_id: str | None = None
    """``null`` = top level."""
    position: int | None = None
    """Among the new siblings (default: last)."""


class KbDraftSave(ApiRequest, kw_only=True):
    title: str | None = None
    doc: dict[str, Any] | None = None
    base_revision_id: str | None = None
    """The draft the editor loaded; a newer draft of another author → 409 ``stale_draft``."""
    source: Literal['editor', 'markdown', 'import'] = 'editor'


class KbDraftOut(ApiResponse, kw_only=True):
    revision_id: str
    title: str
    status: PageStatus
    saved_at: datetime


class KbPublishRequest(ApiRequest, kw_only=True):
    note: str | None = None


class KbRevisionOut(ApiResponse, kw_only=True):
    id: str
    title: str
    source: str
    version: int | None = None
    note: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    is_draft: bool = False
    is_published: bool = False


class KbRevisionDetailOut(KbRevisionOut, kw_only=True):
    doc: dict[str, Any]


class KbLockRequest(ApiRequest, kw_only=True):
    force: bool = False
    """Take over another editor's lock (after confirmation)."""


# --- attachments ----------------------------------------------------------------------------------


class KbAttachmentOut(ApiResponse, kw_only=True):
    id: str
    page_id: str
    filename: str
    mime: str
    size: int
    created_by: str | None = None
    created_by_name: str | None = None
    created_at: datetime


class KbDownloadOut(ApiResponse, kw_only=True):
    url: str
    """Signed, expires after ``FILE_URL_SECONDS`` (5 min)."""
    filename: str
    mime: str
    expires_at: datetime


# --- home / search --------------------------------------------------------------------------------


class KbPageSummaryOut(ApiResponse, kw_only=True):
    id: str
    space_id: str
    space_name: str
    title: str
    owner_id: str | None = None
    published_at: datetime | None = None
    verified_until: datetime | None = None
    review_status: ReviewStatus
    snippet: str | None = None
    """Search only: text around the first match."""


class KbHomeOut(ApiResponse, kw_only=True):
    recent: list[KbPageSummaryOut]
    """Recently published pages the caller can read."""
    spaces: list[KbSpaceOut]
    """Readable spaces, the caller's member spaces first."""
    review: list[KbPageSummaryOut]
    """Pages the caller owns whose verification expired or ends within 14 days."""
