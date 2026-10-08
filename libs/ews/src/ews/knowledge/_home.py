"""Home data and simple search, trimmed to what the caller can read (Kb-0104): published pages of readable spaces
only. Full search (attachments, filters, typo tolerance) and Ask are K4 (🚧)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from db.models.knowledge import KbPage
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import case, or_, select

from ews.security import RequestScope
from ews.shared import utcnow

from ._access import SpaceAccess, readable_spaces
from ._rules import REVIEW_DUE_DAYS, like_pattern, review_status, search_terms, snippet
from ._spaces import published_counts, space_out
from .schemas import KbHomeOut, KbPageSummaryOut


def _summary(
    page: KbPage, spaces: dict[UUID, SpaceAccess], terms: list[str] | None = None
) -> KbPageSummaryOut:
    return KbPageSummaryOut(
        id=str(page.id),
        space_id=str(page.space_id),
        space_name=spaces[page.space_id].space.name,
        title=page.published_title or page.title,
        owner_id=str(page.owner_id) if page.owner_id else None,
        published_at=page.published_at,
        verified_until=page.verified_until,
        review_status=review_status(page.verified_at, page.verified_until, utcnow()),
        snippet=snippet(page.search_text, terms) if terms is not None else None,
    )


def _published(space_ids: list[UUID]):  # noqa: ANN202 - SQLAlchemy select
    return select(KbPage).where(
        KbPage.space_id.in_(space_ids),
        KbPage.deleted_at.is_(None),
        KbPage.published_revision_id.is_not(None),
    )


async def _spaces(
    session: DBAsyncScopedSession, scope: RequestScope, space_id: UUID | None = None
) -> dict[UUID, SpaceAccess]:
    return {
        a.space.id: a
        for a in await readable_spaces(session, scope, [space_id] if space_id else None)
    }


async def recent_pages(
    session: DBAsyncScopedSession, spaces: dict[UUID, SpaceAccess], limit: int = 10
) -> list[KbPageSummaryOut]:
    if not spaces:
        return []
    stmt = _published(list(spaces)).order_by(KbPage.published_at.desc()).limit(limit)
    return [_summary(p, spaces) for p in await session.scalars(stmt)]


async def review_pages(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    spaces: dict[UUID, SpaceAccess] | None = None,
    limit: int = 100,
) -> list[KbPageSummaryOut]:
    """Published pages the caller owns whose verification expired or ends within ``REVIEW_DUE_DAYS`` (Kb-0303)."""
    spaces = spaces if spaces is not None else await _spaces(session, scope)
    if not spaces:
        return []
    stmt = (
        _published(list(spaces))
        .where(
            KbPage.owner_id == scope.user_id,
            KbPage.verified_until.is_not(None),
            KbPage.verified_until <= utcnow() + timedelta(days=REVIEW_DUE_DAYS),
        )
        .order_by(KbPage.verified_until)
        .limit(limit)
    )
    return [_summary(p, spaces) for p in await session.scalars(stmt)]


async def home(session: DBAsyncScopedSession, scope: RequestScope) -> KbHomeOut:
    spaces = await _spaces(session, scope)
    ordered = sorted(
        spaces.values(),
        key=lambda a: (
            a.role in (None, 'kb_space_viewer'),
            -a.space.updated_at.timestamp(),
        ),
    )[:12]
    counts = await published_counts(session, [a.space.id for a in ordered])
    return KbHomeOut(
        recent=await recent_pages(session, spaces),
        spaces=[space_out(a, counts.get(a.space.id, 0)) for a in ordered],
        review=await review_pages(session, scope, spaces, limit=20),
    )


async def search(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    q: str | None,
    space_id: UUID | None = None,
    limit: int = 20,
) -> list[KbPageSummaryOut]:
    """Every term in the published title or text (case-insensitive); title matches first, then the newest."""
    terms = search_terms(q)
    if not terms:
        return []
    spaces = await _spaces(session, scope, space_id)
    if not spaces:
        return []
    stmt = _published(list(spaces))
    for term in terms:
        pattern = like_pattern(term)
        stmt = stmt.where(
            or_(
                KbPage.published_title.ilike(pattern, escape='\\'),
                KbPage.search_text.ilike(pattern, escape='\\'),
            )
        )
    title_first = case(
        (KbPage.published_title.ilike(like_pattern(terms[0]), escape='\\'), 0), else_=1
    )
    stmt = stmt.order_by(title_first, KbPage.published_at.desc()).limit(
        max(1, min(limit, 50))
    )
    return [_summary(p, spaces, terms) for p in await session.scalars(stmt)]
