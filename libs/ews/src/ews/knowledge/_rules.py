"""Pure rules of the Knowledge Center (no I/O): limits, slugs, visibility → implicit role, page status,
review status, soft lock, search helpers. Spec: taas-specs/knowledge/knowledge-app-spec.md."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from foundation.exceptions import ClientException

from ews.shared import slugify  # noqa: F401 (re-exported: one slug rule for every app)

MAX_DEPTH = 10
"""Levels of the page tree (Kb-0300)."""
LOCK_TTL = timedelta(minutes=2)
"""Soft lock lifetime; the editor refreshes it (``POST /pages/{id}/lock``) and every autosave extends it."""
DEFAULT_REVIEW_DAYS = 180
MAX_REVIEW_DAYS = 3650
REVIEW_DUE_DAYS = 14
"""``GET /knowledge/review``: verification expired or ending within this many days (Kb-0303)."""
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
FILE_URL_SECONDS = 300
"""Lifetime of an attachment download URL (Sto-0200: 1–5 min)."""
MAX_TITLE = 200

VIEWER = 'kb_space_viewer'
"""Role the visibility audience holds implicitly (Kb-0100)."""

Visibility = Literal['tenant', 'organization', 'restricted']
VISIBILITIES: tuple[str, ...] = ('tenant', 'organization', 'restricted')
PageStatus = Literal['draft', 'published', 'changed']
ReviewStatus = Literal['verified', 'due', 'expired', 'unverified']

_SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
_ICON = re.compile(r'^[a-z0-9-]{1,40}$')


def slug_error(slug: str, max_len: int) -> str | None:
    if not slug or len(slug) > max_len or not _SLUG.match(slug):
        return (
            f'slug must be lowercase letters, digits and single hyphens (max {max_len})'
        )
    return None


def clean_text(
    value: str | None, what: str, max_len: int, *, required: bool = False
) -> str | None:
    text = (value or '').strip()
    if required and not text:
        raise ClientException(detail=f'{what} is required')
    if len(text) > max_len:
        raise ClientException(detail=f'{what} must be at most {max_len} characters')
    return text or None


def clean_title(value: str | None) -> str:
    title = clean_text(value, 'title', MAX_TITLE, required=True)
    assert title is not None
    return title


def clean_icon(value: str | None) -> str | None:
    if value in (None, ''):
        return None
    if not _ICON.match(value):
        raise ClientException(
            detail='icon must be an icon name (lowercase letters, digits, hyphens)'
        )
    return value


def clean_color(value: str | None) -> str | None:
    if value in (None, ''):
        return None
    if not _COLOR.match(value):
        raise ClientException(detail='color must be #rrggbb')
    return value.lower()


def clean_visibility(value: str) -> str:
    if value not in VISIBILITIES:
        raise ClientException(
            detail=f'visibility must be one of {", ".join(VISIBILITIES)}'
        )
    return value


def clean_review_days(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not 1 <= value <= MAX_REVIEW_DAYS:
        raise ClientException(
            detail=f'review_interval_days must be between 1 and {MAX_REVIEW_DAYS}'
        )
    return value


# --- access ---------------------------------------------------------------------------------------


class SpaceAudience(Protocol):
    visibility: str
    organization_id: UUID
    include_sub_orgs: bool


def implicit_role(
    space: SpaceAudience, org_path: str, memberships: Iterable[tuple[UUID, str]]
) -> str | None:
    """``kb_space_viewer`` when the caller is in the space's visibility audience (Kb-0100), else ``None``.

    ``memberships`` = ``(organization id, path)`` of the caller's organizations in the space's tenant;
    ``org_path`` = path of the space's organization. ``restricted``: explicit members only.
    """
    if space.visibility == 'tenant':
        return VIEWER
    if space.visibility == 'organization':
        for org_id, path in memberships:
            if org_id == space.organization_id or (
                space.include_sub_orgs and path.startswith(org_path)
            ):
                return VIEWER
    return None


# --- pages ----------------------------------------------------------------------------------------


class PageState(Protocol):
    draft_revision_id: UUID | None
    published_revision_id: UUID | None
    locked_by: UUID | None
    locked_until: datetime | None


def page_status(page: PageState) -> PageStatus:
    if page.published_revision_id is None:
        return 'draft'
    return (
        'published'
        if page.draft_revision_id in (None, page.published_revision_id)
        else 'changed'
    )


def lock_holder(page: PageState, now: datetime) -> UUID | None:
    """The user holding an unexpired soft lock."""
    if page.locked_by and page.locked_until and page.locked_until > now:
        return page.locked_by
    return None


def review_status(
    verified_at: datetime | None, verified_until: datetime | None, now: datetime
) -> ReviewStatus:
    """``verified`` · ``due`` (ends within ``REVIEW_DUE_DAYS``) · ``expired`` · ``unverified`` (never verified)."""
    if verified_until is None:
        return 'verified' if verified_at else 'unverified'
    if verified_until < now:
        return 'expired'
    if verified_until <= now + timedelta(days=REVIEW_DUE_DAYS):
        return 'due'
    return 'verified'


def verified_until(base: datetime | None, interval_days: int | None) -> datetime | None:
    return base + timedelta(days=interval_days) if base and interval_days else None


def check_create_depth(parent_depth: int | None) -> None:
    """400 when a new page under a parent at ``parent_depth`` (``None`` = top level) exceeds ``MAX_DEPTH``."""
    if parent_depth is not None and parent_depth + 1 >= MAX_DEPTH:
        raise ClientException(detail=f'the tree is limited to {MAX_DEPTH} levels')


def visible_tree_ids(pages: Iterable[tuple[UUID, UUID | None, bool]]) -> set[UUID]:
    """Pages a reader sees in the tree: published, under published ancestors only. ``pages`` =
    ``(id, parent id, published)`` ordered parents first (by depth)."""
    visible: set[UUID] = set()
    for page_id, parent_id, published in pages:
        if published and (parent_id is None or parent_id in visible):
            visible.add(page_id)
    return visible


# --- search ---------------------------------------------------------------------------------------


def search_terms(q: str | None, limit: int = 8) -> list[str]:
    return [t for t in (q or '').split() if t][:limit]


def like_pattern(term: str) -> str:
    """``%term%`` with ``\\``, ``%`` and ``_`` escaped (``ESCAPE '\\'``)."""
    escaped = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def snippet(text: str | None, terms: list[str], width: int = 160) -> str:
    """About ``width`` characters of ``text`` around the first matching term."""
    body = ' '.join((text or '').split())
    if not body:
        return ''
    lower = body.lower()
    hits = [i for i in (lower.find(t.lower()) for t in terms) if i >= 0]
    start = max(0, min(hits) - width // 3) if hits else 0
    end = min(len(body), start + width)
    return f'{"…" if start else ""}{body[start:end].strip()}{"…" if end < len(body) else ""}'
