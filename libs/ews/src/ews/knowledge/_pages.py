"""Page tree (Kb-0300): create (blank / template / document), read (draft for editors, published for readers —
Kb-0103), owner + review interval (Kb-0303), move / reorder (≤ ``MAX_DEPTH`` levels), soft delete of a subtree.

The tree is a materialized path of ids (``ews.shared`` tree helpers); content lives in revisions (``_revisions``).
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import msgspec
from db.models.knowledge import KbPage, KbPageRevision, KbSpace
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select, text, update

from ews.security import RequestScope
from ews.shared import (
    ConflictException,
    ancestor_ids,
    check_move,
    child_path,
    depth_of,
    move_subtree,
    parse_uuid,
    user_names,
    utcnow,
)

from ._access import PageAccess, SpaceAccess
from ._document import check_document, empty_document, migrate_document
from ._rules import (
    DEFAULT_REVIEW_DAYS,
    MAX_DEPTH,
    check_create_depth,
    clean_review_days,
    clean_title,
    lock_holder,
    page_status,
    review_status,
    slug_error,
    slugify,
    verified_until,
    visible_tree_ids,
)
from ._spaces import space_ref
from ._templates import get_template
from .schemas import (
    KbBreadcrumbOut,
    KbLockOut,
    KbPageCreate,
    KbPageDetailOut,
    KbPageMove,
    KbPageOut,
    KbPageUpdate,
)

PAGE_SLUG_MAX = 80


def lock_out(
    page: KbPage, scope: RequestScope, names: dict[UUID, str], now: datetime
) -> KbLockOut | None:
    holder = lock_holder(page, now)
    if holder is None:
        return None
    return KbLockOut(
        locked=holder == scope.user_id,
        holder_id=str(holder),
        holder_name=names.get(holder),
        locked_until=page.locked_until,
    )


def page_out(
    page: KbPage,
    scope: RequestScope,
    *,
    editor: bool,
    names: dict[UUID, str],
    now: datetime | None = None,
) -> KbPageOut:
    """Editors see the draft title, the status and the lock; readers the published title."""
    now = now or utcnow()
    return KbPageOut(
        id=str(page.id),
        space_id=str(page.space_id),
        parent_id=str(page.parent_id) if page.parent_id else None,
        title=page.title if editor else (page.published_title or page.title),
        slug=page.slug,
        position=page.position,
        depth=page.depth,
        status=page_status(page) if editor else 'published',
        owner_id=str(page.owner_id) if page.owner_id else None,
        owner_name=names.get(page.owner_id) if page.owner_id else None,
        review_interval_days=page.review_interval_days,
        verified_at=page.verified_at,
        verified_until=page.verified_until,
        review_status=review_status(page.verified_at, page.verified_until, now),
        published_at=page.published_at,
        lock=lock_out(page, scope, names, now) if editor else None,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


async def _space_pages(session: DBAsyncScopedSession, space_id: UUID) -> list[KbPage]:
    return list(
        await session.scalars(
            select(KbPage)
            .where(KbPage.space_id == space_id, KbPage.deleted_at.is_(None))
            .order_by(KbPage.depth, KbPage.position, KbPage.created_at)
        )
    )


async def tree(
    session: DBAsyncScopedSession, scope: RequestScope, access: SpaceAccess
) -> list[KbPageOut]:
    """Flat tree (parents first, ``parent_id`` + ``position``). Readers: published pages under published
    ancestors only."""
    pages = await _space_pages(session, access.space.id)
    editor = access.is_editor
    if not editor:
        visible = visible_tree_ids(
            (p.id, p.parent_id, p.published_revision_id is not None) for p in pages
        )
        pages = [p for p in pages if p.id in visible]
    now = utcnow()
    names = await user_names(
        session,
        [p.owner_id for p in pages]
        + ([lock_holder(p, now) for p in pages] if editor else []),
    )
    return [page_out(p, scope, editor=editor, names=names, now=now) for p in pages]


async def find_page(
    session: DBAsyncScopedSession, space: KbSpace, page_id: object, what: str = 'page'
) -> KbPage:
    """A live page of ``space`` (400 when missing: used for body references such as ``parent_id``)."""
    pid = parse_uuid(page_id, what, not_found=False)
    page = await session.scalar(
        select(KbPage).where(
            KbPage.id == pid, KbPage.space_id == space.id, KbPage.deleted_at.is_(None)
        )
    )
    if page is None:
        raise ClientException(detail=f'{what} not found in this space')
    return page


async def _slug_taken(
    session: DBAsyncScopedSession,
    space_id: UUID,
    slug: str,
    exclude: UUID | None = None,
) -> bool:
    stmt = select(KbPage.id).where(
        KbPage.space_id == space_id, KbPage.slug == slug, KbPage.deleted_at.is_(None)
    )
    if exclude:
        stmt = stmt.where(KbPage.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _free_slug(session: DBAsyncScopedSession, space_id: UUID, title: str) -> str:
    base = slugify(title, PAGE_SLUG_MAX - 4) or 'page'
    slug, n = base, 2
    while await _slug_taken(session, space_id, slug):
        slug, n = f'{base}-{n}', n + 1
    return slug


async def _place(
    session: DBAsyncScopedSession, page: KbPage, position: int | None
) -> None:
    """Put ``page`` at ``position`` among its live siblings (default: last) and renumber them."""
    parent = (
        KbPage.parent_id.is_(None)
        if page.parent_id is None
        else KbPage.parent_id == page.parent_id
    )
    siblings = list(
        await session.scalars(
            select(KbPage)
            .where(
                KbPage.space_id == page.space_id,
                parent,
                KbPage.deleted_at.is_(None),
                KbPage.id != page.id,
            )
            .order_by(KbPage.position, KbPage.created_at)
        )
    )
    index = len(siblings) if position is None else max(0, min(position, len(siblings)))
    siblings.insert(index, page)
    for i, sibling in enumerate(siblings):
        sibling.position = i


async def create_page(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    access: SpaceAccess,
    data: KbPageCreate,
) -> KbPage:
    space = access.space
    source = 'editor'
    doc: dict[str, Any] = empty_document()
    title = data.title
    if data.template:
        template = get_template(data.template)
        doc, source, title = template['doc'], 'template', title or template['title']
    elif data.doc is not None:
        doc = copy.deepcopy(data.doc)
    title = clean_title(title or 'Untitled')
    check_document(doc)
    parent = (
        await find_page(session, space, data.parent_id, 'parent page')
        if data.parent_id
        else None
    )
    check_create_depth(parent.depth if parent else None)
    interval = (
        DEFAULT_REVIEW_DAYS
        if data.review_interval_days is msgspec.UNSET
        else clean_review_days(data.review_interval_days)
    )
    page_id = uuid.uuid7()
    path = child_path(parent.path if parent else None, page_id)
    page = KbPage(
        id=page_id,
        tenant_id=space.tenant_id,
        space_id=space.id,
        parent_id=parent.id if parent else None,
        path=path,
        depth=depth_of(path),
        position=0,
        title=title,
        slug=await _free_slug(session, space.id, title),
        owner_id=scope.user_id,
        review_interval_days=interval,
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(page)
    await _place(session, page, data.position)
    await session.flush()
    revision = KbPageRevision(
        id=uuid.uuid7(),
        tenant_id=space.tenant_id,
        space_id=space.id,
        page_id=page.id,
        title=title,
        doc=doc,
        source=source,
        author_id=scope.user_id,
    )
    session.add(revision)
    page.draft_revision_id = revision.id
    space.updated_at = utcnow()
    await session.flush()
    return page


async def _breadcrumbs(
    session: DBAsyncScopedSession, page: KbPage, editor: bool
) -> list[KbBreadcrumbOut]:
    ids = ancestor_ids(page.path)
    if not ids:
        return []
    rows = {
        p.id: p
        for p in await session.scalars(
            select(KbPage).where(KbPage.id.in_(ids), KbPage.deleted_at.is_(None))
        )
    }
    return [
        KbBreadcrumbOut(
            id=str(i),
            title=rows[i].title
            if editor
            else (rows[i].published_title or rows[i].title),
        )
        for i in ids
        if i in rows
    ]


async def page_detail(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    view: Literal['draft', 'published'] | None = None,
) -> KbPageDetailOut:
    """Editors get the draft (``view='published'``: the live version), readers the published version."""
    page, editor = pa.page, pa.access.is_editor
    if not editor or view == 'published':
        view, revision_id = 'published', page.published_revision_id
    else:
        view, revision_id = 'draft', page.draft_revision_id
    revision = await session.get(KbPageRevision, revision_id) if revision_id else None
    if view == 'published' and revision is None:
        raise NotFoundException(detail='the page is not published')
    now = utcnow()
    names = await user_names(session, [page.owner_id, lock_holder(page, now)])
    base = page_out(page, scope, editor=editor, names=names, now=now)
    fields = {f: getattr(base, f) for f in base.__struct_fields__}
    if revision is not None:
        fields['title'] = revision.title
    return KbPageDetailOut(
        **fields,
        view=view,
        doc=migrate_document(revision.doc) if revision else empty_document(),
        revision_id=str(revision.id) if revision else None,
        version=revision.version if revision else None,
        draft_revision_id=str(page.draft_revision_id)
        if editor and page.draft_revision_id
        else None,
        published_revision_id=str(page.published_revision_id)
        if page.published_revision_id
        else None,
        permissions=sorted(pa.access.permissions),
        breadcrumbs=await _breadcrumbs(session, page, editor),
        space=space_ref(pa.space),
    )


async def _tenant_user(
    session: DBAsyncScopedSession, tenant_id: UUID, user_id: UUID
) -> bool:
    row = await session.execute(
        text(
            'select 1 from taas_user_account u where u.id = :u and (u.tenant_id = :t or exists '
            '(select 1 from taas_organization_members m where m.user_id = u.id and m.tenant_id = :t)) limit 1'
        ),
        {'u': user_id, 't': tenant_id},
    )
    return row.first() is not None


async def update_page(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    pa: PageAccess,
    data: KbPageUpdate,
) -> KbPage:
    """Slug, owner and review interval (the title is part of the draft: ``PUT /pages/{id}/draft``)."""
    page = pa.page
    if data.slug is not None and data.slug != page.slug:
        if error := slug_error(data.slug, PAGE_SLUG_MAX):
            raise ClientException(detail=error)
        if await _slug_taken(session, page.space_id, data.slug, exclude=page.id):
            raise ConflictException(
                detail=f'a page of this space already uses the slug {data.slug}',
                extra={'code': 'slug_taken'},
            )
        page.slug = data.slug
    if data.owner_id is not None:
        owner = parse_uuid(data.owner_id, 'owner', not_found=False)
        if not await _tenant_user(session, page.tenant_id, owner):
            raise ClientException(detail='the owner must be a user of this tenant')
        page.owner_id = owner
    if data.review_interval_days is not msgspec.UNSET:
        page.review_interval_days = clean_review_days(data.review_interval_days)
        page.verified_until = verified_until(
            page.verified_at or page.published_at, page.review_interval_days
        )
    page.updated_by, page.updated_at = scope.user_id, utcnow()
    await session.flush()
    return page


async def move_page(
    session: DBAsyncScopedSession, scope: RequestScope, pa: PageAccess, data: KbPageMove
) -> KbPage:
    """Move under another page of the space (``parent_id`` null = top level) and / or reorder among siblings."""
    page = pa.page
    parent = (
        await find_page(session, pa.space, data.parent_id, 'parent page')
        if data.parent_id
        else None
    )
    if (parent.id if parent else None) != page.parent_id:
        deepest = await session.scalar(
            select(func.max(KbPage.depth)).where(
                KbPage.space_id == page.space_id,
                KbPage.path.like(f'{page.path}%'),
                KbPage.deleted_at.is_(None),
            )
        )
        check_move(
            page.path,
            parent.path if parent else None,
            max_depth=MAX_DEPTH,
            subtree_height=(deepest or page.depth) - page.depth,
        )
        await move_subtree(session, KbPage, page, parent)
    await _place(session, page, data.position)
    page.updated_by, page.updated_at = scope.user_id, utcnow()
    await session.flush()
    return page


async def delete_page(
    session: DBAsyncScopedSession, scope: RequestScope, pa: PageAccess
) -> int:
    """Soft delete of the page and its sub-pages; returns how many pages were deleted."""
    now = utcnow()
    result = await session.execute(
        update(KbPage)
        .where(
            KbPage.space_id == pa.page.space_id,
            KbPage.path.like(f'{pa.page.path}%'),
            KbPage.deleted_at.is_(None),
        )
        .values(deleted_at=now, updated_by=scope.user_id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    pa.page.deleted_at = now
    await session.flush()
    return int(result.rowcount or 0)
