"""Virtual views over the drives the caller can read (File-0206: every result is permission-trimmed on the server):
home, recent, starred, search by name / type / owner / date (File-0400, name + metadata part)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from db.models.files import FileActivity, FileNode, FileStar
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import parse_uuid

from . import _access as access
from . import _drives as drives
from . import _nodes as nodes
from ._rules import like_pattern
from .schemas import FileTypeFilter, FilesHomeOut, FileNodeOut, FileNodePage


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
    limit: int = 50,
    offset: int = 0,
) -> FileNodePage:
    """Live folders and files of the readable drives (or one of them: another drive → 404) by name."""
    ids = [c.drive.id for c in ctxs]
    if drive_id:
        wanted = parse_uuid(drive_id, 'drive')
        if wanted not in ids:
            raise NotFoundException(detail='drive not found')
        ids = [wanted]
    limit = min(max(limit, 1), 200)
    where = [FileNode.drive_id.in_(ids), nodes.live()]
    if q and q.strip():
        where.append(FileNode.name.ilike(like_pattern(q.strip()), escape='\\'))
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
    total = (
        await session.scalar(select(func.count()).select_from(FileNode).where(*where))
        or 0
    )
    rows = await session.scalars(
        select(FileNode)
        .where(*where)
        .order_by(FileNode.updated_at.desc(), FileNode.id.desc())
        .limit(limit)
        .offset(max(offset, 0))
    )
    items = await nodes.node_outputs(
        session, scope, list(rows), drive_names=_names(ctxs)
    )
    return FileNodePage(items=items, total=int(total), limit=limit, offset=offset)


async def home(session: DBAsyncScopedSession, scope: RequestScope) -> FilesHomeOut:
    ctxs = await drives.visible_drives(session, scope)
    return FilesHomeOut(
        drives=await drives.drive_outputs(session, scope, ctxs),
        recent=await recent(session, scope, ctxs, limit=12),
    )
