"""Blog rules — pure functions, unit-tested (``tests/unit/test_blog_rules.py``): editorial status machine
(Blog-0102 / 0103), slugs and former slugs (Blog-0106…0109), reading time, blog settings, author links, schedule
instants, the own-post rule, the pure parts of the public snapshot (blog-publishing-spec §5).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from foundation.exceptions import ClientException

from ews.shared import slugify  # noqa: F401 (re-exported: the one slug rule, Blog-0106)
from ews.sites._document import plain_text
from ews.sites._rules import RESERVED_PATHS, page_slug_error, site_slug_error

POST_STATUSES = (
    'draft',
    'in_review',
    'scheduled',
    'published',
    'unpublished',
    'archived',
)
"""Editorial status of a post; ``published`` ⇔ a live revision (``published_revision_id``)."""

REVISION_SOURCES = ('visual', 'markdown', 'ai', 'import')
"""Sources a client may send; ``restore`` is set by the server."""

LOCK_TTL = timedelta(seconds=120)
"""Soft lock lifetime; the editor refreshes it while open (Blog-0101)."""
REVISION_WINDOW = timedelta(seconds=60)
"""Autosaves of the same user and source within this window update the working draft revision."""

WORDS_PER_MINUTE = 230
_CJK = re.compile('[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
"""Kana, CJK ideographs, Hangul: scripts without spaces, one character = one word (same rule as the web)."""
_LOCALE = re.compile(r'^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$')
_LINK_URL = re.compile(r'^(https?://[^\s<>"]+|mailto:[^\s<>"]+)$', re.I)


# --- status machine -------------------------------------------------------------------------------


class InvalidTransition(ValueError):
    """The action does not apply to the post's current status (→ 409 ``invalid_transition``)."""


ACTIONS: dict[str, frozenset[str]] = {
    'submit': frozenset({'draft', 'unpublished'}),
    'request_changes': frozenset({'in_review'}),
    'approve': frozenset({'in_review'}),
    'publish': frozenset(
        {'draft', 'in_review', 'scheduled', 'published', 'unpublished'}
    ),
    'schedule': frozenset({'draft', 'in_review', 'scheduled', 'unpublished'}),
    'unpublish': frozenset({'published', 'scheduled'}),
    'archive': frozenset(
        {'draft', 'in_review', 'scheduled', 'published', 'unpublished'}
    ),
    'unarchive': frozenset({'archived'}),
}
"""Action → statuses it applies to."""


def transition(
    action: str, status: str, *, was_published: bool = False, scheduled: bool = False
) -> str:
    """The status after ``action`` (``was_published`` = the post went live once; ``scheduled`` = ``approve``
    with a date). Raises ``InvalidTransition``.

    ``draft`` —submit→ ``in_review`` —request_changes→ ``draft``; ``approve`` / ``publish`` → ``published``
    (or ``scheduled``); ``unpublish`` takes a post off the blog (a scheduled one back to ``draft`` /
    ``unpublished``); ``archive`` / ``unarchive``.
    """
    allowed = ACTIONS.get(action)
    if allowed is None:
        raise InvalidTransition(f'unknown action {action}')
    if status not in allowed:
        raise InvalidTransition(
            f'cannot {action.replace("_", " ")} a post that is {status.replace("_", " ")}'
        )
    if action == 'submit':
        return 'in_review'
    if action == 'request_changes':
        return 'draft'
    if action == 'approve':
        return 'scheduled' if scheduled else 'published'
    if action == 'publish':
        return 'published'
    if action == 'schedule':
        return 'scheduled'
    if action == 'archive':
        return 'archived'
    # unpublish (published / scheduled) and unarchive
    if action == 'unpublish' and status == 'published':
        return 'unpublished'
    return 'unpublished' if was_published else 'draft'


# --- who may edit ---------------------------------------------------------------------------------


def is_own(
    user_id: UUID, created_by: UUID | None, author_user_ids: Iterable[UUID | None]
) -> bool:
    """A post is the user's own when the user created it or is linked to one of its author profiles."""
    return created_by == user_id or user_id in set(author_user_ids)


def can_edit(permissions: Collection[str], own: bool) -> bool:
    """``blog.post:update`` (editors, admins), or ``update_own`` (authors) on their own posts."""
    return 'blog.post:update' in permissions or (
        'blog.post:update_own' in permissions and own
    )


# --- slugs, locale ----------------------------------------------------------------------------------


def blog_slug_error(slug: str) -> str | None:
    """Same rule as site slugs: both live under ``<org>.<SITES_DOMAIN>/<slug>``."""
    return site_slug_error(slug)


RESERVED_POST_SLUGS = frozenset(
    {'page', 'category', 'tag', 'author', 'feed.xml', 'feed.json', *RESERVED_PATHS}
)
"""Paths of the public blog that a post may not take (Blog-0109): pagination, taxonomy and author lists, feeds,
plus the site reserved paths."""
MAX_FORMER_SLUGS = 20


def term_slug_error(slug: str) -> str | None:
    """Categories, tags and authors: lowercase words joined by single hyphens, ≤ 80 characters."""
    return page_slug_error(slug)


def post_slug_error(slug: str) -> str | None:
    """Posts: the rule of ``term_slug_error`` and not a reserved path of the public blog (Blog-0109)."""
    if error := page_slug_error(slug):
        return error
    if slug in RESERVED_POST_SLUGS:
        return f'"{slug}" is reserved for the pages of the blog'
    return None


def remember_slug(former: Iterable[str], old: str, new: str) -> list[str]:
    """Former slugs after ``old`` → ``new`` (Blog-0108): ``old`` appended (newest last), ``new`` removed (an
    address cannot redirect to itself), no duplicates, the last ``MAX_FORMER_SLUGS`` kept."""
    kept = [s for s in dict.fromkeys(former) if s not in (old, new)]
    if old and old != new:
        kept.append(old)
    return kept[-MAX_FORMER_SLUGS:]


def locale_error(locale: str) -> str | None:
    if not isinstance(locale, str) or len(locale) > 16 or not _LOCALE.match(locale):
        return 'locale must be a language tag such as en, fr or pt-BR'
    return None


# --- reading time -----------------------------------------------------------------------------------


def reading_time(doc: dict[str, Any]) -> tuple[int, int]:
    """``(words, minutes)`` of a post body at 230 words per minute, rounded, at least one minute when there is
    text — the rule of the web editor (``@taas/doc-editor`` ``wordCount`` / ``readingMinutes``)."""
    text = plain_text(doc, limit=10_000_000)
    cjk = len(_CJK.findall(text))
    words = len(_CJK.sub(' ', text).split()) + cjk
    return words, (max(1, math.floor(words / WORDS_PER_MINUTE + 0.5)) if words else 0)


# --- settings, links --------------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    'posts_per_page': 10,
    'default_author_id': None,
    'feed_enabled': True,
    'feed_full_text': False,
    'ai_voice': None,
}


def clean_settings(raw: dict[str, Any]) -> dict[str, Any]:
    """Validated blog settings (only the keys of ``DEFAULT_SETTINGS``; ``None`` resets a key)."""
    if not isinstance(raw, dict):
        raise ClientException(detail='settings must be an object')
    unknown = sorted(set(raw) - set(DEFAULT_SETTINGS))
    if unknown:
        raise ClientException(detail=f'unknown setting {unknown[0]}')
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key == 'posts_per_page':
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 50
            ):
                raise ClientException(detail='settings.posts_per_page must be 1 to 50')
        elif key == 'default_author_id':
            try:
                value = str(UUID(str(value)))
            except ValueError as error:
                raise ClientException(
                    detail='settings.default_author_id must be an author id'
                ) from error
        elif key in ('feed_enabled', 'feed_full_text'):
            if not isinstance(value, bool):
                raise ClientException(detail=f'settings.{key} must be true or false')
        elif key == 'ai_voice':
            if not isinstance(value, str) or len(value) > 1000:
                raise ClientException(
                    detail='settings.ai_voice must be at most 1000 characters'
                )
            value = value.strip() or None
            if value is None:
                continue
        out[key] = value
    return out


def clean_links(raw: Any) -> list[dict[str, str]]:
    """Author profile links: at most 10 ``{label, url}`` with an http(s) / mailto URL."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 10:
        raise ClientException(detail='links must be a list of at most 10 items')
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ClientException(detail='each link is {label, url}')
        label, url = item.get('label'), item.get('url')
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            raise ClientException(detail='link label must be 1 to 60 characters')
        if not isinstance(url, str) or len(url) > 500 or not _LINK_URL.match(url):
            raise ClientException(detail='link url must be an http(s) or mailto: URL')
        out.append({'label': label.strip(), 'url': url})
    return out


# --- scheduling -------------------------------------------------------------------------------------


def schedule_instant(
    value: datetime, timezone: str | None, now: datetime
) -> tuple[datetime, str]:
    """``(instant in UTC, zone name)`` of a schedule (Blog-0103): a naive ``value`` is wall time in
    ``timezone`` (IANA, default UTC), an aware one is taken as is. Must be in the future."""
    name = (timezone or 'UTC').strip() or 'UTC'
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ClientException(detail=f'unknown time zone {name}') from error
    instant = value.replace(tzinfo=zone) if value.tzinfo is None else value
    instant = instant.astimezone(ZoneInfo('UTC'))
    if instant <= now:
        raise ClientException(detail='scheduled_at must be in the future')
    return instant, name


# --- public snapshot (blog-publishing-spec §5) ----------------------------------------------------------

SNAPSHOT_SCHEMA = 1
SNAPSHOT_HEADER = ('release_id', 'version', 'generated_at')
"""Fields of a snapshot that change with every release (left out when comparing contents)."""


def public_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The settings the renderer needs (defaults filled in)."""
    merged = {**DEFAULT_SETTINGS, **settings}
    return {
        'posts_per_page': merged['posts_per_page'],
        'feed_full_text': merged['feed_full_text'],
        'feed_enabled': merged['feed_enabled'],
    }


def public_slugs(
    live: Iterable[tuple[str, Iterable[str]]], deleted: Iterable[Iterable[str]]
) -> tuple[list[list[str]], list[str]]:
    """``(former slugs per live post, gone slugs)``: a current slug wins over a former one (first post wins a
    former slug claimed twice — pass the newest first), a former one over a gone one (Blog-0303).

    ``live`` = ``(slug, former_slugs)`` of the published posts; ``deleted`` = every slug (current + former) of
    each deleted post that had been published.
    """
    live = [(slug, list(former)) for slug, former in live]
    taken = {slug for slug, _ in live}
    formers: list[list[str]] = []
    for _, former in live:
        kept = [s for s in dict.fromkeys(former) if s not in taken]
        taken.update(kept)
        formers.append(kept)
    gone = sorted({s for slugs in deleted for s in slugs if s and s not in taken})
    return formers, gone


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def snapshot_post(
    post: Any,
    revision: Any,
    former_slugs: list[str],
    *,
    categories: Collection[str],
    tags: Collection[str],
    authors: Collection[str],
) -> dict[str, Any]:
    """A post of the snapshot: the address of the post now (``slug``, ``former_slugs``) and everything else
    from its **published revision** (title + ``meta`` at publish time). References to deleted categories, tags
    or authors are dropped."""
    meta = revision.meta or {}
    seo = meta.get('seo') or {}
    cover = meta.get('cover_asset_id')
    minutes = meta.get('reading_minutes')
    if minutes is None:
        minutes = reading_time(revision.doc or {})[1]
    category = meta.get('category_id')
    return {
        'id': str(post.id),
        'slug': post.slug,
        'former_slugs': former_slugs,
        'title': revision.title,
        'subtitle': meta.get('subtitle'),
        'excerpt': meta.get('excerpt'),
        'published_at': _iso(post.published_at),
        'updated_at': meta.get('live_at') or _iso(post.published_at),
        'reading_minutes': minutes,
        'featured': bool(meta.get('featured')),
        'revision_id': str(revision.id),
        'cover': {'asset_id': cover, 'alt': meta.get('cover_alt')} if cover else None,
        'category_id': category if category in categories else None,
        'tag_ids': [t for t in meta.get('tag_ids') or [] if t in tags],
        'author_ids': [a for a in meta.get('author_ids') or [] if a in authors],
        'seo': {
            'title': seo.get('title'),
            'description': seo.get('description'),
            'canonical': seo.get('canonical'),
            'og_image': seo.get('og_image'),
            'noindex': bool(meta.get('noindex')),
        },
    }


def snapshot_asset_refs(
    posts: Iterable[Mapping[str, Any]], authors: Iterable[Mapping[str, Any]]
) -> set[UUID]:
    """Media of the release (not of the bodies): covers, social images, author avatars."""
    refs: set[UUID] = set()
    values = [
        *((p.get('cover') or {}).get('asset_id') for p in posts),
        *((p.get('seo') or {}).get('og_image') for p in posts),
        *(a.get('avatar') for a in authors),
    ]
    for value in values:
        if isinstance(value, str) and value:
            try:
                refs.add(UUID(value.removeprefix('asset:')))
            except ValueError:
                continue
    return refs


def content_digest(snapshot: Mapping[str, Any]) -> str:
    """Hash of a snapshot without its header: equal digests = the public output did not change."""
    body = {k: v for k, v in snapshot.items() if k not in SNAPSHOT_HEADER}
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
