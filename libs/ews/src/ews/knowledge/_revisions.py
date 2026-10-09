"""Drafts, versions and verification of a page (Kb-0302, Kb-0303).

- **Draft**: one revision with ``version`` null, autosaved in place while it is the same author's; another author
  (or the first save after a publish) starts a new draft revision. ``base_revision_id`` = the draft the editor
  loaded: a newer draft of someone else → 409 ``stale_draft``.
- **Publish**: the draft becomes version *n* (immutable); readers get it, search indexes its text. The first
  publish counts as the first verification when the page has a review interval.
- **Discard**: the draft goes back to the published version; the discarded draft stays in the history (restorable).
- **Soft lock**: ``locked_by`` + ``locked_until`` (``LOCK_TTL``); saving / publishing while someone else holds it →
  409 ``locked``; ``force`` takes it over.
- **Verify**: ``verified_until = now + review_interval_days``.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any
from uuid import UUID

from db.models.knowledge import KbPage, KbPageRevision
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import ConflictException, parse_uuid, user_names, utcnow

from ._access import PageAccess
from ._document import check_document, migrate_document, search_text
from ._rules import LOCK_TTL, clean_title, lock_holder, page_status, verified_until
from .schemas import (
    KbDraftOut,
    KbDraftSave,
    KbLockOut,
    KbRevisionDetailOut,
    KbRevisionOut,
)


async def _check_lock(
    session: DBAsyncScopedSession, scope: RequestScope, page: KbPage
) -> UUID | None:
    holder = lock_holder(page, utcnow())
    if holder and holder != scope.user_id:
        names = await user_names(session, [holder])
        raise ConflictException(
            detail=f'{names.get(holder, "Someone")} is editing this page',
            extra={'code': 'locked'},
        )
    return holder


async def _draft(session: DBAsyncScopedSession, page: KbPage) -> KbPageRevision | None:
    return (
        await session.get(KbPageRevision, page.draft_revision_id)
        if page.draft_revision_id
        else None
    )


async def _write_draft(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    page: KbPage,
    *,
    title: str,
    doc: dict[str, Any],
    source: str,
    note: str | None = None,
    reuse: bool = True,
) -> KbPageRevision:
    current = await _draft(session, page)
    now = utcnow()
    if (
        reuse
        and current is not None
        and current.version is None
        and current.author_id == scope.user_id
    ):
        current.title, current.doc, current.source, current.updated_at = (
            title,
            doc,
            source,
            now,
        )
        revision = current
    else:
        revision = KbPageRevision(
            id=uuid.uuid7(),
            tenant_id=page.tenant_id,
            space_id=page.space_id,
            page_id=page.id,
            title=title,
            doc=doc,
            source=source,
            author_id=scope.user_id,
            note=(note or None) and note[:500],
        )
        session.add(revision)
        page.draft_revision_id = revision.id
    page.title = title
    if page.locked_by == scope.user_id:
        page.locked_until = now + LOCK_TTL
    page.updated_by, page.updated_at = scope.user_id, now
    await session.flush()
    return revision


async def save_draft(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    data: KbDraftSave,
) -> KbDraftOut:
    """Autosave title and / or body of the draft (Kb-0302)."""
    page = pa.page
    if data.title is None and data.doc is None:
        raise ClientException(detail='nothing to save: send title and / or doc')
    await _check_lock(session, scope, page)
    current = await _draft(session, page)
    if (
        data.base_revision_id
        and current is not None
        and str(current.id) != data.base_revision_id
        and current.author_id != scope.user_id
    ):
        raise ConflictException(
            detail='the page was changed by someone else: reload it',
            extra={'code': 'stale_draft'},
        )
    title = clean_title(data.title) if data.title is not None else page.title
    if data.doc is not None:
        doc = check_document(data.doc)
    else:
        doc = (
            copy.deepcopy(current.doc)
            if current
            else {'schemaVersion': 1, 'sections': []}
        )
    revision = await _write_draft(
        session, scope, page, title=title, doc=doc, source=data.source
    )
    return KbDraftOut(
        revision_id=str(revision.id),
        title=title,
        status=page_status(page),
        saved_at=revision.updated_at,
    )


async def publish(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    note: str | None = None,
) -> KbPage:
    """The draft becomes the next version, visible to readers and searchable."""
    page = pa.page
    await _check_lock(session, scope, page)
    if (
        page.draft_revision_id is None
        or page.draft_revision_id == page.published_revision_id
    ):
        raise ConflictException(
            detail='nothing to publish: the page has no unpublished changes',
            extra={'code': 'no_changes'},
        )
    revision = await _draft(session, page)
    if revision is None:  # pragma: no cover - dangling id
        raise NotFoundException(detail='draft not found')
    check_document(revision.doc)
    last = await session.scalar(
        select(func.max(KbPageRevision.version)).where(
            KbPageRevision.page_id == page.id
        )
    )
    now = utcnow()
    revision.version, revision.published_at, revision.published_by = (
        (last or 0) + 1,
        now,
        scope.user_id,
    )
    if note:
        revision.note = note.strip()[:500] or None
    page.published_revision_id, page.published_title = revision.id, revision.title
    page.published_at, page.published_by = now, scope.user_id
    page.search_text = search_text(revision.doc)
    if page.review_interval_days and page.verified_at is None:
        page.verified_at, page.verified_by = now, scope.user_id
        page.verified_until = verified_until(now, page.review_interval_days)
    page.updated_by, page.updated_at = scope.user_id, now
    pa.space.updated_at = now
    await session.flush()
    return page


async def discard_draft(
    session: DBAsyncScopedSession, scope: RequestScope, pa: PageAccess
) -> KbDraftOut:
    """Drop the unpublished changes (Kb-0302): the draft becomes the published version again; the discarded draft
    stays in the history (versions sheet → restore)."""
    page = pa.page
    await _check_lock(session, scope, page)
    if page.published_revision_id is None:
        raise ConflictException(
            detail='this page was never published: there is no version to go back to',
            extra={'code': 'never_published'},
        )
    if page.draft_revision_id == page.published_revision_id:
        raise ConflictException(
            detail='nothing to discard: the page has no unpublished changes',
            extra={'code': 'no_changes'},
        )
    published = await session.get(KbPageRevision, page.published_revision_id)
    if published is None:  # pragma: no cover - dangling id
        raise NotFoundException(detail='published version not found')
    now = utcnow()
    page.draft_revision_id = published.id
    page.title = published.title
    page.updated_by, page.updated_at = scope.user_id, now
    await session.flush()
    return KbDraftOut(
        revision_id=str(published.id),
        title=published.title,
        status=page_status(page),
        saved_at=now,
    )


def _revision_out(
    r: KbPageRevision, page: KbPage, names: dict[UUID, str]
) -> dict[str, Any]:
    return {
        'id': str(r.id),
        'title': r.title,
        'source': r.source,
        'version': r.version,
        'note': r.note,
        'author_id': str(r.author_id) if r.author_id else None,
        'author_name': names.get(r.author_id) if r.author_id else None,
        'created_at': r.created_at,
        'updated_at': r.updated_at,
        'published_at': r.published_at,
        'is_draft': r.id == page.draft_revision_id,
        'is_published': r.id == page.published_revision_id,
    }


async def list_revisions(
    session: DBAsyncScopedSession, page: KbPage, limit: int = 100
) -> list[KbRevisionOut]:
    rows = list(
        await session.scalars(
            select(KbPageRevision)
            .where(KbPageRevision.page_id == page.id)
            .order_by(KbPageRevision.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
    names = await user_names(session, [r.author_id for r in rows])
    return [KbRevisionOut(**_revision_out(r, page, names)) for r in rows]


async def _revision(
    session: DBAsyncScopedSession, page: KbPage, revision_id: object
) -> KbPageRevision:
    rid = parse_uuid(revision_id, 'revision')
    revision = await session.scalar(
        select(KbPageRevision).where(
            KbPageRevision.id == rid, KbPageRevision.page_id == page.id
        )
    )
    if revision is None:
        raise NotFoundException(detail='revision not found')
    return revision


async def get_revision(
    session: DBAsyncScopedSession, page: KbPage, revision_id: object
) -> KbRevisionDetailOut:
    r = await _revision(session, page, revision_id)
    names = await user_names(session, [r.author_id])
    return KbRevisionDetailOut(
        **_revision_out(r, page, names), doc=migrate_document(r.doc)
    )


async def restore_revision(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    revision_id: object,
) -> KbDraftOut:
    """Copy a revision (title + body) into a new draft; publish to make it live."""
    page = pa.page
    await _check_lock(session, scope, page)
    source = await _revision(session, page, revision_id)
    label = (
        f'version {source.version}'
        if source.version
        else f'the draft of {source.created_at:%Y-%m-%d %H:%M}'
    )
    revision = await _write_draft(
        session,
        scope,
        page,
        title=source.title,
        doc=copy.deepcopy(migrate_document(source.doc)),
        source='restore',
        note=f'Restored from {label}',
        reuse=False,
    )
    return KbDraftOut(
        revision_id=str(revision.id),
        title=revision.title,
        status=page_status(page),
        saved_at=revision.updated_at,
    )


async def lock(
    session: DBAsyncScopedSession, scope: RequestScope, page: KbPage, *, force: bool
) -> KbLockOut:
    """Take / refresh the soft lock; held by someone else → ``locked: false`` with the holder (unless ``force``)."""
    now = utcnow()
    holder = lock_holder(page, now)
    if not holder or holder == scope.user_id or force:
        page.locked_by, page.locked_until, holder = (
            scope.user_id,
            now + LOCK_TTL,
            scope.user_id,
        )
        await session.flush()
    names = await user_names(session, [holder])
    return KbLockOut(
        locked=holder == scope.user_id,
        holder_id=str(holder),
        holder_name=names.get(holder),
        locked_until=page.locked_until,
    )


async def unlock(
    session: DBAsyncScopedSession, scope: RequestScope, page: KbPage
) -> None:
    if page.locked_by == scope.user_id:
        page.locked_by, page.locked_until = None, None
        await session.flush()


async def verify(
    session: DBAsyncScopedSession, scope: RequestScope, pa: PageAccess
) -> KbPage:
    """Mark the published content as still correct (Kb-0303)."""
    page = pa.page
    if page.published_revision_id is None:
        raise ClientException(detail='publish the page before verifying it')
    now = utcnow()
    page.verified_at, page.verified_by = now, scope.user_id
    page.verified_until = verified_until(now, page.review_interval_days)
    page.updated_at = now
    await session.flush()
    return page
