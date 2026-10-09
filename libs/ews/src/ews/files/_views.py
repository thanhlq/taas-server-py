"""Virtual views over the drives the caller can read (File-0206: every result is permission-trimmed on the server):
home, recent, starred, search (File-0400) by name (trigram index), **content** (local full-text index of the
current versions, ``taas_file_contents.tsv``), type, owner, date — names first, then by text rank."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import msgspec

from db.models.files import FileActivity, FileContent, FileNode, FileStar
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from sqlalchemy import Select, and_, case, func, literal, null, or_, select, true

from ews.security import RequestScope
from ews.shared import parse_uuid

from . import _access as access
from . import _drives as drives
from . import _nodes as nodes
from ._rules import SNIPPET_START, SNIPPET_STOP, like_pattern, prefix_tsquery
from .schemas import (
    FileNodeOut,
    FilesHomeOut,
    FileSearchHitOut,
    FileSearchPage,
    FileTypeFilter,
)

_HEADLINE = (
    f'StartSel={SNIPPET_START}, StopSel={SNIPPET_STOP}, MaxWords=24, MinWords=8, MaxFragments=2, '
    'FragmentDelimiter=" … "'
)
_HEADLINE_CHARS = 50_000


def _names(ctxs: list[access.DriveCtx]) -> dict[UUID, str]:
    return {c.drive.id: c.drive.name for c in ctxs}


async def recent(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctxs: list[access.DriveCtx],
    limit: int = 30,
) -> list[FileNodeOut]:
    """Files of the readable drives, latest first by their last change or the caller's last action on them."""
    ids = [c.drive.id for c in ctxs]
    if not ids:
        return []
    mine = (
        select(
            FileActivity.node_id.label('node_id'),
            func.max(FileActivity.created_at).label('at'),
        )
        .where(
            FileActivity.tenant_id == scope.tenant_id,
            FileActivity.actor_id == scope.user_id,
            FileActivity.node_id.is_not(None),
            FileActivity.drive_id.in_(ids),
        )
        .group_by(FileActivity.node_id)
        .subquery()
    )
    seen = func.greatest(
        FileNode.updated_at, func.coalesce(mine.c.at, FileNode.updated_at)
    )
    rows = await session.scalars(
        select(FileNode)
        .outerjoin(mine, mine.c.node_id == FileNode.id)
        .where(FileNode.drive_id.in_(ids), FileNode.kind == 'file', nodes.live())
        .order_by(seen.desc(), FileNode.id.desc())
        .limit(min(max(limit, 1), 100))
    )
    return await nodes.node_outputs(
        session, scope, list(rows), drive_names=_names(ctxs)
    )


async def starred(
    session: DBAsyncScopedSession, scope: RequestScope, ctxs: list[access.DriveCtx]
) -> list[FileNodeOut]:
    ids = [c.drive.id for c in ctxs]
    if not ids:
        return []
    rows = await session.scalars(
        select(FileNode)
        .join(FileStar, FileStar.node_id == FileNode.id)
        .where(
            FileStar.user_id == scope.user_id,
            FileStar.tenant_id == scope.tenant_id,
            FileNode.drive_id.in_(ids),
            nodes.live(),
        )
        .order_by(FileStar.created_at.desc())
        .limit(500)
    )
    return await nodes.node_outputs(
        session, scope, list(rows), drive_names=_names(ctxs)
    )


async def search(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctxs: list[access.DriveCtx],
    *,
    q: str | None = None,
    file_type_: FileTypeFilter | None = None,
    drive_id: str | None = None,
    owner: str | None = None,
    modified_after: datetime | None = None,
    content: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> FileSearchPage:
    """Live folders and files of the readable drives (or one of them: another drive → 404) whose name contains
    ``q`` or — ``content`` — whose current version's text has every word of ``q`` (as prefixes)."""
    ids = [c.drive.id for c in ctxs]
    if drive_id:
        wanted = parse_uuid(drive_id, 'drive')
        if wanted not in ids:
            raise NotFoundException(detail='drive not found')
        ids = [wanted]
    limit = min(max(limit, 1), 200)
    where = [FileNode.drive_id.in_(ids), nodes.live()]
    if file_type_:
        where.append(nodes.type_clause(file_type_))
    if owner:
        where.append(
            FileNode.created_by
            == (
                scope.user_id
                if owner == 'me'
                else parse_uuid(owner, 'owner', not_found=False)
            )
        )
    if modified_after:
        where.append(FileNode.updated_at >= modified_after)
    text_q = (q or '').strip()
    query = prefix_tsquery(text_q) if content and text_q else None
    name_hit = (
        FileNode.name.ilike(like_pattern(text_q), escape='\\') if text_q else true()
    )
    if query:
        tsq = func.to_tsquery('simple', query)
        content_hit = FileContent.tsv.op('@@')(tsq)
        where.append(or_(name_hit, content_hit))
        rank = func.coalesce(func.ts_rank(FileContent.tsv, tsq), 0.0)
        snippet = case(
            (
                content_hit,
                func.ts_headline(
                    'simple',
                    func.left(FileContent.text, _HEADLINE_CHARS),
                    tsq,
                    _HEADLINE,
                ),
            ),
            else_=null(),
        )
    else:
        where.append(name_hit)
        rank, snippet = literal(0.0), null()

    def scoped(stmt: Select[Any]) -> Select[Any]:
        if query:  # the text of the current version only
            stmt = stmt.outerjoin(
                FileContent,
                and_(
                    FileContent.node_id == FileNode.id,
                    FileContent.version_id == FileNode.current_version_id,
                ),
            )
        return stmt.where(*where)

    total = (
        await session.scalar(
            scoped(select(func.count(FileNode.id)).select_from(FileNode))
        )
        or 0
    )
    rows = (
        await session.execute(
            scoped(select(FileNode, rank, snippet, name_hit))
            .order_by(
                case((name_hit, 0), else_=1),
                rank.desc(),
                FileNode.updated_at.desc(),
                FileNode.id.desc(),
            )
            .limit(limit)
            .offset(max(offset, 0))
        )
    ).all()
    items = await nodes.node_outputs(
        session, scope, [r[0] for r in rows], drive_names=_names(ctxs)
    )
    hits = [
        FileSearchHitOut(
            **msgspec.structs.asdict(item),
            match='name' if row[3] or not query else 'content',
            snippet=row[2],
            rank=round(float(row[1] or 0), 6),
        )
        for item, row in zip(items, rows, strict=True)
    ]
    return FileSearchPage(items=hits, total=int(total), limit=limit, offset=offset)


async def home(session: DBAsyncScopedSession, scope: RequestScope) -> FilesHomeOut:
    ctxs = await drives.visible_drives(session, scope)
    return FilesHomeOut(
        drives=await drives.drive_outputs(session, scope, ctxs),
        recent=await recent(session, scope, ctxs, limit=12),
    )
