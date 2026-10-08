"""Folders and files of a drive (File-0303, File-0306): materialized-path tree (``ews.shared`` helpers, ≤ 20
levels), names unique per folder (case-insensitive, live items), rename / color, move inside the drive, copy a
file, stars, trash (subtree) → restore → purge (storage objects deleted, rows kept for the activity log)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

import msgspec
from db.models.files import FileDrive, FileNode, FileStar, FileVersion
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import (
    ColumnElement,
    and_,
    case,
    delete,
    func,
    not_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ews.security import RequestScope
from ews.shared import (
    ConflictException,
    ancestor_ids,
    check_move,
    child_path,
    move_subtree,
    parse_uuid,
    user_names,
    utcnow,
)

from . import _access as access
from . import _storage as storage
from ._activity import record
from ._rules import (
    like_pattern,
    MAX_DEPTH,
    clean_color,
    clean_name,
    file_type,
    free_name,
    split_ext,
    type_patterns,
)
from ._settings import files_settings
from .schemas import (
    FileTypeFilter,
    FileFolderCreate,
    FileNodeCopy,
    FileNodeDetailOut,
    FileNodeOut,
    FileNodeRef,
    NodeSort,
    FileNodeUpdate,
)


def live() -> ColumnElement[bool]:
    return and_(FileNode.trashed_at.is_(None), FileNode.deleted_at.is_(None))


def name_conflict(name: str) -> ConflictException:
    return ConflictException(
        detail=f'an item named "{name}" already exists here',
        extra={'code': 'name_conflict'},
    )


async def flush_unique(session: DBAsyncScopedSession, name: str) -> None:
    """Flush; a concurrent same-name item (``ux_taas_file_nodes_name``) → 409 ``name_conflict``."""
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as error:
        if 'ux_taas_file_nodes_name' in str(error.orig):
            raise name_conflict(name) from error
        raise


# --- lookups --------------------------------------------------------------------------------------


async def get_folder(
    session: DBAsyncScopedSession, drive_id: UUID, folder_id: object | None
) -> FileNode | None:
    """A live folder of the drive (``None`` / empty = the drive's top level); 400 otherwise."""
    if folder_id in (None, ''):
        return None
    fid = parse_uuid(folder_id, 'parent_id', not_found=False)
    folder = await session.scalar(
        select(FileNode).where(
            FileNode.id == fid,
            FileNode.drive_id == drive_id,
            FileNode.kind == 'folder',
            live(),
        )
    )
    if folder is None:
        raise ClientException(detail='parent_id: no such folder in this drive')
    return folder


def _in_folder(drive_id: UUID, parent_id: UUID | None) -> ColumnElement[bool]:
    parent = (
        FileNode.parent_id.is_(None)
        if parent_id is None
        else FileNode.parent_id == parent_id
    )
    return and_(FileNode.drive_id == drive_id, parent, live())


async def find_by_name(
    session: DBAsyncScopedSession, drive_id: UUID, parent_id: UUID | None, name: str
) -> FileNode | None:
    return await session.scalar(
        select(FileNode)
        .where(
            _in_folder(drive_id, parent_id), func.lower(FileNode.name) == name.lower()
        )
        .limit(1)
    )


async def taken_names(
    session: DBAsyncScopedSession, drive_id: UUID, parent_id: UUID | None
) -> set[str]:
    rows = await session.scalars(
        select(func.lower(FileNode.name)).where(_in_folder(drive_id, parent_id))
    )
    return set(rows)


def child_depth(parent: FileNode | None) -> int:
    depth = parent.depth + 1 if parent is not None else 0
    if depth >= MAX_DEPTH:
        raise ClientException(
            detail=f'folders are limited to {MAX_DEPTH} levels',
            extra={'code': 'too_deep'},
        )
    return depth


async def ensure_folders(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    parent: FileNode | None,
    names: Sequence[str],
) -> FileNode | None:
    """The folder ``parent/a/b`` of a dropped folder (created when missing; a file with that name → 409)."""
    for raw in names:
        name = clean_name(raw, 'folder name')
        existing = await find_by_name(
            session, ctx.drive.id, parent.id if parent else None, name
        )
        if existing is not None and existing.kind == 'folder':
            parent = existing
            continue
        if existing is not None:
            raise name_conflict(name)
        parent = await _new_folder(session, scope, ctx, parent, name, None)
    return parent


# --- outputs --------------------------------------------------------------------------------------


async def node_outputs(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    nodes: Sequence[FileNode],
    *,
    drive_names: dict[UUID, str] | None = None,
) -> list[FileNodeOut]:
    ids = [n.id for n in nodes]
    starred = (
        set(
            await session.scalars(
                select(FileStar.node_id).where(
                    FileStar.user_id == scope.user_id, FileStar.node_id.in_(ids)
                )
            )
        )
        if ids
        else set()
    )
    names = await user_names(
        session, [u for n in nodes for u in (n.created_by, n.updated_by)]
    )
    return [
        _out(
            n, FileNodeOut, n.id in starred, names, (drive_names or {}).get(n.drive_id)
        )
        for n in nodes
    ]


def _out(
    node: FileNode,
    cls: type[FileNodeOut],
    starred: bool,
    names: dict[UUID, str],
    drive_name: str | None,
    **extra,
) -> FileNodeOut:  # noqa: ANN003
    return cls(
        id=str(node.id),
        drive_id=str(node.drive_id),
        drive_name=drive_name,
        parent_id=str(node.parent_id) if node.parent_id else None,
        kind=node.kind,  # type: ignore[arg-type]
        type=file_type(node.kind, node.mime),
        name=node.name,
        ext=node.ext,
        mime=node.mime,
        size=node.size,
        version=node.version,
        current_version_id=str(node.current_version_id)
        if node.current_version_id
        else None,
        color=node.color,
        starred=starred,
        depth=node.depth,
        created_by=str(node.created_by) if node.created_by else None,
        created_by_name=names.get(node.created_by) if node.created_by else None,
        updated_by=str(node.updated_by) if node.updated_by else None,
        updated_by_name=names.get(node.updated_by) if node.updated_by else None,
        created_at=node.created_at,
        updated_at=node.updated_at,
        trashed_at=node.trashed_at,
        trashed_by=str(node.trashed_by) if node.trashed_by else None,
        **extra,
    )


async def node_output(
    session: DBAsyncScopedSession, scope: RequestScope, node: FileNode
) -> FileNodeOut:
    return (await node_outputs(session, scope, [node]))[0]


async def node_detail(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    node: FileNode,
    ctx: access.DriveCtx,
) -> FileNodeDetailOut:
    """The item with its breadcrumb and the caller's ``files.*`` permissions."""
    ids = ancestor_ids(node.path)
    rows = (
        {
            r.id: r.name
            for r in await session.execute(
                select(FileNode.id, FileNode.name).where(FileNode.id.in_(ids))
            )
        }
        if ids
        else {}
    )
    starred = await session.scalar(
        select(FileStar.id).where(
            FileStar.user_id == scope.user_id, FileStar.node_id == node.id
        )
    )
    names = await user_names(session, [node.created_by, node.updated_by])
    out = _out(
        node,
        FileNodeDetailOut,
        starred is not None,
        names,
        ctx.drive.name,
        ancestors=[FileNodeRef(id=str(i), name=rows[i]) for i in ids if i in rows],
        permissions=await access.permissions(scope, ctx),
    )
    assert isinstance(out, FileNodeDetailOut)
    return out


# --- listing --------------------------------------------------------------------------------------


def type_clause(file_type_: FileTypeFilter) -> ColumnElement[bool]:
    """Search / list filter on the quick-tab type (``other`` = files of none of the other types)."""
    if file_type_ in ('folder', 'file'):
        return FileNode.kind == file_type_
    doc_exact, doc_prefixes = type_patterns('document')
    document = or_(
        FileNode.mime.in_(doc_exact),
        *(FileNode.mime.like(f'{p}%') for p in doc_prefixes),
    )
    media = or_(*(FileNode.mime.like(f'{t}/%') for t in ('image', 'video', 'audio')))
    if file_type_ == 'document':
        return and_(FileNode.kind == 'file', document)
    if file_type_ == 'other':
        return and_(
            FileNode.kind == 'file',
            or_(FileNode.mime.is_(None), not_(or_(document, media))),
        )
    return and_(FileNode.kind == 'file', FileNode.mime.like(f'{file_type_}/%'))


_SORT = {
    'name': func.lower(FileNode.name),
    'updated': FileNode.updated_at,
    'created': FileNode.created_at,
    'size': FileNode.size,
}


async def list_children(
    session: DBAsyncScopedSession,
    ctx: access.DriveCtx,
    parent: FileNode | None,
    *,
    file_type_: FileTypeFilter | None = None,
    q: str | None = None,
    sort: NodeSort = 'name',
    order: str = 'asc',
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[FileNode], int]:
    """Folders first, then the sort column; ``q`` = name contains (this folder only)."""
    where = [_in_folder(ctx.drive.id, parent.id if parent else None)]
    if file_type_:
        where.append(type_clause(file_type_))
    if q and q.strip():
        where.append(FileNode.name.ilike(like_pattern(q.strip()), escape='\\'))
    total = (
        await session.scalar(select(func.count()).select_from(FileNode).where(*where))
        or 0
    )
    column = _SORT[sort]
    stmt = (
        select(FileNode)
        .where(*where)
        .order_by(
            case((FileNode.kind == 'folder', 0), else_=1),
            column.desc() if order == 'desc' else column.asc(),
            FileNode.id,
        )
        .limit(min(max(limit, 1), 500))
        .offset(max(offset, 0))
    )
    return list(await session.scalars(stmt)), int(total)


# --- folders, rename, move, copy ------------------------------------------------------------------


async def _new_folder(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    parent: FileNode | None,
    name: str,
    color: str | None,
) -> FileNode:
    depth = child_depth(parent)
    if await find_by_name(session, ctx.drive.id, parent.id if parent else None, name):
        raise name_conflict(name)
    node_id = uuid.uuid7()
    node = FileNode(
        id=node_id,
        tenant_id=scope.tenant_id,
        drive_id=ctx.drive.id,
        parent_id=parent.id if parent else None,
        kind='folder',
        name=name,
        path=child_path(parent.path if parent else None, node_id),
        depth=depth,
        color=color,
        version=0,
        size=0,
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(node)
    await flush_unique(session, name)
    record(session, scope, ctx.drive.id, 'folder.created', node)
    return node


async def create_folder(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    data: FileFolderCreate,
) -> FileNode:
    parent = await get_folder(session, ctx.drive.id, data.parent_id)
    return await _new_folder(
        session, scope, ctx, parent, clean_name(data.name), clean_color(data.color)
    )


async def update_node(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    data: FileNodeUpdate,
) -> None:
    """Rename and / or color (File-0303)."""
    if data.name is not None:
        name = clean_name(data.name)
        if name != node.name:
            other = await find_by_name(session, node.drive_id, node.parent_id, name)
            if other is not None and other.id != node.id:
                raise name_conflict(name)
            record(
                session,
                scope,
                ctx.drive.id,
                'node.renamed',
                node,
                old_name=node.name,
                new_name=name,
            )
            node.name = name
            if node.kind == 'file':
                node.ext = split_ext(name)[1]
    if data.color is not msgspec.UNSET:
        node.color = clean_color(data.color)
    node.updated_by = scope.user_id
    node.updated_at = utcnow()
    await flush_unique(session, node.name)


async def _subtree_height(session: DBAsyncScopedSession, node: FileNode) -> int:
    deepest = await session.scalar(
        select(func.max(FileNode.depth)).where(
            FileNode.drive_id == node.drive_id, FileNode.path.like(f'{node.path}%')
        )
    )
    return int(deepest or node.depth) - node.depth


async def move_node(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    parent_id: str | None,
) -> None:
    """Move inside the drive (another drive's folder → 400); the subtree's paths are rewritten in one statement."""
    parent = await get_folder(session, node.drive_id, parent_id)
    if (parent.id if parent else None) == node.parent_id:
        return
    check_move(
        node.path,
        parent.path if parent else None,
        max_depth=MAX_DEPTH,
        subtree_height=await _subtree_height(session, node),
    )
    if await find_by_name(
        session, node.drive_id, parent.id if parent else None, node.name
    ):
        raise name_conflict(node.name)
    old_parent = node.parent_id
    await move_subtree(session, FileNode, node, parent)
    node.updated_by = scope.user_id
    node.updated_at = utcnow()
    await flush_unique(session, node.name)
    record(
        session,
        scope,
        ctx.drive.id,
        'node.moved',
        node,
        from_id=old_parent,
        to_id=parent.id if parent else None,
    )


async def current_version(
    session: DBAsyncScopedSession, node: FileNode, version_id: object | None = None
) -> FileVersion:
    vid = (
        node.current_version_id
        if version_id in (None, '')
        else parse_uuid(version_id, 'version')
    )
    version = (
        await session.scalar(
            select(FileVersion).where(
                FileVersion.id == vid, FileVersion.node_id == node.id
            )
        )
        if vid
        else None
    )
    if version is None:
        raise NotFoundException(detail='version not found')
    return version


async def copy_file(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    data: FileNodeCopy,
) -> FileNode:
    """A copy of a file's current version in the same drive (*name (1).ext* when the name is taken)."""
    if node.kind != 'file':
        raise ClientException(detail='only files can be copied')
    parent_id = node.parent_id if data.parent_id is msgspec.UNSET else data.parent_id
    parent = await get_folder(session, node.drive_id, parent_id)
    depth = child_depth(parent)
    name = free_name(
        clean_name(data.name) if data.name else node.name,
        await taken_names(session, node.drive_id, parent.id if parent else None),
    )
    source = await current_version(session, node)
    new_id, version_id = uuid.uuid7(), uuid.uuid7()
    key = storage.version_key(node.drive_id, new_id, version_id)
    store = await storage.store_for(scope.tenant_id)
    await store.copy(source.key, key)
    now = utcnow()
    try:
        copy = FileNode(
            id=new_id,
            tenant_id=scope.tenant_id,
            drive_id=node.drive_id,
            parent_id=parent.id if parent else None,
            kind='file',
            name=name,
            path=child_path(parent.path if parent else None, new_id),
            depth=depth,
            color=node.color,
            current_version_id=version_id,
            version=1,
            size=source.size,
            mime=source.mime,
            ext=split_ext(name)[1],
            created_by=scope.user_id,
            updated_by=scope.user_id,
        )
        session.add(copy)
        await flush_unique(session, name)
        session.add(
            FileVersion(
                id=version_id,
                tenant_id=scope.tenant_id,
                node_id=new_id,
                number=1,
                key=key,
                size=source.size,
                mime=source.mime,
                checksum=source.checksum,
                scan_status=source.scan_status,
                uploaded_by=scope.user_id,
                created_at=now,
            )
        )
        await session.flush()
    except Exception:
        await storage.delete_keys(scope.tenant_id, [key])
        raise
    record(session, scope, ctx.drive.id, 'file.copied', copy, source_id=node.id)
    return copy


# --- stars ----------------------------------------------------------------------------------------


async def set_star(
    session: DBAsyncScopedSession, scope: RequestScope, node: FileNode, starred: bool
) -> None:
    if starred:
        now = utcnow()
        await session.execute(
            pg_insert(FileStar)
            .values(
                id=uuid.uuid7(),
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                node_id=node.id,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(constraint='uq_taas_file_stars_user_node')
        )
    else:
        await session.execute(
            delete(FileStar).where(
                FileStar.user_id == scope.user_id, FileStar.node_id == node.id
            )
        )


# --- trash (File-0306) ----------------------------------------------------------------------------


async def trash_node(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
) -> None:
    """The item and its live subtree go to the trash together (``trash_root_id`` = the item)."""
    now = utcnow()
    await session.execute(
        update(FileNode)
        .where(
            FileNode.drive_id == node.drive_id,
            FileNode.path.like(f'{node.path}%'),
            live(),
        )
        .values(trashed_at=now, trashed_by=scope.user_id, trash_root_id=node.id)
        .execution_options(synchronize_session=False)
    )
    node.trashed_at, node.trashed_by, node.trash_root_id = now, scope.user_id, node.id
    record(session, scope, ctx.drive.id, 'node.trashed', node)
    await session.flush()


async def list_trash(
    session: DBAsyncScopedSession,
    ctx: access.DriveCtx,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[FileNode], int]:
    """The items users deleted (not their subtrees), newest first."""
    where = (
        FileNode.drive_id == ctx.drive.id,
        FileNode.trashed_at.is_not(None),
        FileNode.deleted_at.is_(None),
        FileNode.id == FileNode.trash_root_id,
    )
    total = (
        await session.scalar(select(func.count()).select_from(FileNode).where(*where))
        or 0
    )
    rows = await session.scalars(
        select(FileNode)
        .where(*where)
        .order_by(FileNode.trashed_at.desc())
        .limit(min(max(limit, 1), 500))
        .offset(max(offset, 0))
    )
    return list(rows), int(total)


async def restore_node(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
) -> None:
    """Back to its folder (or the top level when that folder is gone), renamed *name (n)* when the name is taken."""
    if node.trash_root_id != node.id:
        raise ClientException(
            detail='this item was deleted with its folder: restore the folder',
            extra={'code': 'not_trash_root'},
        )
    parent = None
    moved = False
    if node.parent_id is not None:
        parent = await session.scalar(
            select(FileNode).where(FileNode.id == node.parent_id, live())
        )
        if parent is None:
            await move_subtree(session, FileNode, node, None)
            moved = True
    name = free_name(
        node.name,
        await taken_names(session, node.drive_id, parent.id if parent else None),
    )
    renamed = name != node.name
    node.name = name
    await session.flush()
    try:
        async with session.begin_nested():
            await session.execute(
                update(FileNode)
                .where(FileNode.trash_root_id == node.id, FileNode.deleted_at.is_(None))
                .values(trashed_at=None, trashed_by=None, trash_root_id=None)
                .execution_options(synchronize_session=False)
            )
    except IntegrityError as error:
        if 'ux_taas_file_nodes_name' in str(error.orig):
            raise name_conflict(name) from error
        raise
    node.trashed_at = node.trashed_by = node.trash_root_id = None
    record(
        session,
        scope,
        ctx.drive.id,
        'node.restored',
        node,
        renamed=renamed,
        moved_to_top_level=moved,
    )
    await session.flush()


async def purge_subtree(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    root: FileNode,
    *,
    reason: str = 'user',
) -> int:
    """Delete for good: the subtree's rows are marked ``deleted_at`` and its storage objects removed."""
    ids = list(
        await session.scalars(
            select(FileNode.id).where(
                FileNode.drive_id == root.drive_id,
                FileNode.path.like(f'{root.path}%'),
                FileNode.deleted_at.is_(None),
            )
        )
    )
    if not ids:
        return 0
    keys = list(
        await session.scalars(
            select(FileVersion.key).where(FileVersion.node_id.in_(ids))
        )
    )
    now = utcnow()
    await session.execute(
        update(FileNode)
        .where(FileNode.id.in_(ids))
        .values(deleted_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.execute(delete(FileStar).where(FileStar.node_id.in_(ids)))
    root.deleted_at = now
    record(
        session,
        scope,
        root.drive_id,
        'node.purged',
        root,
        tenant_id=root.tenant_id,
        items=len(ids),
        reason=reason,
    )
    await session.flush()
    await storage.delete_keys(root.tenant_id, keys)
    return len(ids)


async def empty_trash(
    session: DBAsyncScopedSession, scope: RequestScope, ctx: access.DriveCtx
) -> int:
    count = 0
    while True:
        roots, _ = await list_trash(session, ctx, limit=200)
        if not roots:
            return count
        for root in roots:
            count += await purge_subtree(session, scope, root)


async def purge_expired(
    session: DBAsyncScopedSession,
    *,
    days: int | None = None,
    now: datetime | None = None,
    tenant_id: UUID | None = None,
    limit: int = 200,
) -> int:
    """Retention job (File-0306): purge trash older than ``days`` (``FILES_TRASH_DAYS``, 30) and the files of
    shared drives deleted before that (every tenant, or ``tenant_id``). Returns the number of purged items; the
    caller commits. Worker wiring: 🚧."""
    cutoff = (now or utcnow()) - timedelta(days=days or files_settings().trash_days)
    expired_trash = select(FileNode).where(
        FileNode.deleted_at.is_(None),
        FileNode.id == FileNode.trash_root_id,
        FileNode.trashed_at < cutoff,
    )
    deleted_drives = select(FileDrive.id).where(
        FileDrive.deleted_at.is_not(None), FileDrive.deleted_at < cutoff
    )
    drive_tops = select(FileNode).where(
        FileNode.deleted_at.is_(None),
        FileNode.parent_id.is_(None),
        FileNode.drive_id.in_(deleted_drives),
    )
    if tenant_id is not None:
        expired_trash = expired_trash.where(FileNode.tenant_id == tenant_id)
        drive_tops = drive_tops.where(FileNode.tenant_id == tenant_id)
    count = 0
    for stmt in (expired_trash, drive_tops):
        for root in list(await session.scalars(stmt.limit(limit))):
            if root.deleted_at is None:
                count += await purge_subtree(session, None, root, reason='retention')
    return count
