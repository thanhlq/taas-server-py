"""Uploads, versions and downloads (File-0300, File-0301, File-0206).

- **Through the API**: ``POST /drives/{id}/files`` (multipart) or ``POST /nodes/{id}/versions`` — size limit
  ``FILES_MAX_UPLOAD_MB``, SHA-256 stored.
- **Direct**: ``POST /drives/{id}/uploads`` → ticket (``url`` = provider-signed PUT, or the EWS proxy
  ``PUT /uploads/{token}``) → client PUTs the bytes to a **staging** key → ``POST /uploads/complete`` (size checked
  with ``HEAD``, copied to the version key, staging deleted): a reused upload URL never touches a version.
- Same name in the same folder: ``on_conflict`` = ``version`` (default: a new version, needs
  ``files.item:update``) · ``keep_both`` (*name (1).ext*) · ``skip``.
- Malware scan: P2 — every version is ``scan_status = 'skipped'``; ``pending`` / ``infected`` block downloads.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal
from uuid import UUID

from db.models.files import FileNode, FileVersion
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from foundation.exceptions.http_exceptions import RequestEntityTooLarge
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import ConflictException, child_path, parse_uuid, user_names, utcnow

from . import _access as access
from . import _nodes as nodes
from . import _storage as storage
from ._activity import record
from ._rules import clean_name, free_name, inline_allowed, mime_of, split_ext
from ._settings import FilesSettings, files_settings
from .schemas import (
    FileDownloadOut,
    OnConflict,
    FileUploadRequest,
    FileUploadTicketOut,
    FileVersionOut,
)

type UploadResult = Literal['created', 'versioned', 'skipped']

BLOCKED_SCANS = ('pending', 'infected')


def _check_size(size: int, settings: FilesSettings) -> None:
    if size <= 0:
        raise ClientException(detail='file is empty')
    if size > settings.max_upload_bytes:
        raise RequestEntityTooLarge(
            detail=f'file too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)',
            extra={'code': 'too_large'},
        )


def _split_relative(
    relative_path: str | None, filename: str | None
) -> tuple[list[str], str | None]:
    """``('a/b/report.pdf')`` → ``(['a', 'b'], 'report.pdf')`` — a dropped folder (File-0300)."""
    if not relative_path:
        return [], filename
    parts = [
        p for p in relative_path.replace('\\', '/').split('/') if p not in ('', '.')
    ]
    if not parts or '..' in parts:
        raise ClientException(detail='relative_path is not a valid path')
    return parts[:-1], parts[-1]


async def _resolve(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    parent: FileNode | None,
    name: str,
    on_conflict: OnConflict,
) -> tuple[UploadResult, FileNode | None, str]:
    """``(result, existing file to version | skipped item, final name)``."""
    existing = await nodes.find_by_name(
        session, ctx.drive.id, parent.id if parent else None, name
    )
    if existing is None:
        return 'created', None, name
    if on_conflict == 'skip':
        return 'skipped', existing, name
    if on_conflict == 'keep_both':
        return (
            'created',
            None,
            free_name(
                name,
                await nodes.taken_names(
                    session, ctx.drive.id, parent.id if parent else None
                ),
            ),
        )
    if existing.kind == 'folder':
        raise nodes.name_conflict(name)
    await access.check(scope, ctx, access.ITEM, 'update', what='item')
    return 'versioned', existing, existing.name


async def _add_version(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    *,
    node: FileNode | None,
    parent: FileNode | None,
    name: str,
    node_id: UUID,
    version_id: UUID,
    key: str,
    size: int,
    mime: str,
    checksum: str | None,
    comment: str | None,
    restored_from: int | None = None,
) -> FileNode:
    """A new file (``node`` = ``None``) or a new current version of ``node``."""
    now = utcnow()
    created = node is None
    if node is None:
        node = FileNode(
            id=node_id,
            tenant_id=scope.tenant_id,
            drive_id=ctx.drive.id,
            parent_id=parent.id if parent else None,
            kind='file',
            name=name,
            path=child_path(parent.path if parent else None, node_id),
            depth=nodes.child_depth(parent),
            version=0,
            size=0,
            created_by=scope.user_id,
            updated_by=scope.user_id,
        )
        session.add(node)
        await nodes.flush_unique(session, name)
    else:
        await session.execute(
            select(FileNode.id).where(FileNode.id == node.id).with_for_update()
        )
    number = (
        await session.scalar(
            select(func.max(FileVersion.number)).where(FileVersion.node_id == node.id)
        )
        or 0
    ) + 1
    session.add(
        FileVersion(
            id=version_id,
            tenant_id=scope.tenant_id,
            node_id=node.id,
            number=number,
            key=key,
            size=size,
            mime=mime,
            checksum=checksum,
            comment=(comment or '').strip()[:1000] or None,
            scan_status='skipped',
            restored_from=restored_from,
            uploaded_by=scope.user_id,
            created_at=now,
        )
    )
    node.current_version_id, node.version, node.size, node.mime = (
        version_id,
        number,
        size,
        mime,
    )
    node.ext = split_ext(node.name)[1]
    node.updated_by, node.updated_at = scope.user_id, now
    await session.flush()
    if restored_from is not None:
        record(
            session,
            scope,
            ctx.drive.id,
            'file.version_restored',
            node,
            version=number,
            restored_from=restored_from,
        )
    else:
        record(
            session,
            scope,
            ctx.drive.id,
            'file.uploaded' if created else 'file.version',
            node,
            version=number,
            size=size,
        )
    return node


# --- through the API ------------------------------------------------------------------------------


async def upload_file(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    data: bytes,
    filename: str | None,
    *,
    parent_id: str | None = None,
    relative_path: str | None = None,
    on_conflict: OnConflict = 'version',
    comment: str | None = None,
    declared_mime: str | None = None,
) -> tuple[UploadResult, FileNode]:
    settings = files_settings()
    _check_size(len(data), settings)
    folders, filename = _split_relative(relative_path, filename)
    name = clean_name(filename, 'file name')
    parent = await nodes.get_folder(session, ctx.drive.id, parent_id)
    if folders:
        parent = await nodes.ensure_folders(session, scope, ctx, parent, folders)
    nodes.child_depth(parent)
    result, existing, name = await _resolve(
        session, scope, ctx, parent, name, on_conflict
    )
    if result == 'skipped':
        assert existing is not None
        return result, existing
    mime = mime_of(name, declared_mime)
    node_id, version_id = (existing.id if existing else uuid.uuid7()), uuid.uuid7()
    key = storage.version_key(ctx.drive.id, node_id, version_id)
    await storage.put_bytes(scope.tenant_id, key, data, mime)
    try:
        node = await _add_version(
            session,
            scope,
            ctx,
            node=existing,
            parent=parent,
            name=name,
            node_id=node_id,
            version_id=version_id,
            key=key,
            size=len(data),
            mime=mime,
            checksum=hashlib.sha256(data).hexdigest(),
            comment=comment,
        )
    except Exception:
        await storage.delete_keys(scope.tenant_id, [key])
        raise
    return result, node


async def upload_version(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    data: bytes,
    *,
    comment: str | None = None,
) -> FileNode:
    """*Upload new version* of a file (keeps its name; the type comes from the name)."""
    if node.kind != 'file':
        raise ClientException(detail='versions apply to files only')
    _check_size(len(data), files_settings())
    version_id = uuid.uuid7()
    mime = mime_of(node.name, node.mime)
    key = storage.version_key(node.drive_id, node.id, version_id)
    await storage.put_bytes(scope.tenant_id, key, data, mime)
    try:
        return await _add_version(
            session,
            scope,
            ctx,
            node=node,
            parent=None,
            name=node.name,
            node_id=node.id,
            version_id=version_id,
            key=key,
            size=len(data),
            mime=mime,
            checksum=hashlib.sha256(data).hexdigest(),
            comment=comment,
        )
    except Exception:
        await storage.delete_keys(scope.tenant_id, [key])
        raise


# --- direct upload --------------------------------------------------------------------------------


async def upload_ticket(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    drive_id: str,
    data: FileUploadRequest,
) -> FileUploadTicketOut:
    settings = files_settings()
    _check_size(data.size, settings)
    if data.node_id:
        node, ctx = await access.load_node(
            session, scope, data.node_id, access.ITEM, 'update'
        )
        if node.kind != 'file' or node.drive_id != parse_uuid(drive_id, 'drive'):
            raise ClientException(detail='node_id must be a file of this drive')
        name, parent_id, target, versioned = node.name, node.parent_id, node.id, True
    else:
        ctx = await access.load_drive(session, scope, drive_id, access.ITEM, 'create')
        folders, filename = _split_relative(data.relative_path, data.name)
        name = clean_name(filename, 'file name')
        parent = await nodes.get_folder(session, ctx.drive.id, data.parent_id)
        if folders:
            parent = await nodes.ensure_folders(session, scope, ctx, parent, folders)
        nodes.child_depth(parent)
        result, existing, name = await _resolve(
            session, scope, ctx, parent, name, data.on_conflict
        )
        if result == 'skipped':
            assert existing is not None
            return FileUploadTicketOut(
                skipped=True,
                method='PUT',
                node=await nodes.node_output(session, scope, existing),
                max_bytes=settings.max_upload_bytes,
            )
        parent_id = parent.id if parent else None
        target, versioned = (existing.id, True) if existing else (uuid.uuid7(), False)
    mime = mime_of(name, data.mime)
    version_id = uuid.uuid7()
    claims = {
        't': str(scope.tenant_id),
        'u': str(scope.user_id),
        'd': str(ctx.drive.id),
        'n': str(target),
        'v': str(version_id),
        'p': str(parent_id) if parent_id else '',
        'name': name,
        's': data.size,
        'm': mime,
        'c': data.on_conflict,
        'x': versioned,
    }
    token, exp = storage.upload_token(claims, settings)
    url = await storage.upload_url(
        scope.tenant_id,
        storage.staging_key(ctx.drive.id, version_id),
        mime,
        token,
        settings,
    )
    return FileUploadTicketOut(
        token=token,
        url=url,
        method='PUT',
        headers={'content-type': mime},
        expires_at=storage.as_datetime(exp),
        max_bytes=settings.max_upload_bytes,
    )


def _claims(token: str, scope: RequestScope) -> dict[str, Any]:
    claims = storage.read_upload_token(token)
    if (
        claims is None
        or claims['t'] != str(scope.tenant_id)
        or claims['u'] != str(scope.user_id)
    ):
        raise ClientException(
            detail='upload link expired or invalid', extra={'code': 'upload_expired'}
        )
    return claims


async def receive_upload(token: str, body: bytes, content_length: str | None) -> None:
    """``PUT /uploads/{token}`` (``FILES_DELIVERY=proxy``): the bytes of a direct upload to its staging key, no
    session needed (the signed token is the authorization, like a provider-signed PUT URL)."""
    claims = storage.read_upload_token(token)
    if claims is None:
        raise NotFoundException(detail='upload link expired or invalid')
    limit = min(int(claims['s']), files_settings().max_upload_bytes)
    if (
        content_length and content_length.isdigit() and int(content_length) > limit
    ) or len(body) > limit:
        raise RequestEntityTooLarge(
            detail='file larger than announced', extra={'code': 'too_large'}
        )
    await storage.put_bytes(
        UUID(claims['t']),
        storage.staging_key(claims['d'], claims['v']),
        body,
        claims['m'],
    )


async def complete_upload(
    session: DBAsyncScopedSession, scope: RequestScope, token: str, comment: str | None
) -> tuple[UploadResult, FileNode]:
    """Register a direct upload (idempotent: a completed token returns its file)."""
    claims = _claims(token, scope)
    version_id = UUID(claims['v'])
    done = await session.scalar(select(FileVersion).where(FileVersion.id == version_id))
    if done is not None:
        node, _ = await access.load_node(
            session, scope, done.node_id, access.ITEM, 'read', trashed=None
        )
        return ('versioned' if claims['x'] else 'created'), node
    staging = storage.staging_key(claims['d'], claims['v'])
    store = await storage.store_for(scope.tenant_id)
    info = await store.head(staging)
    if info is None:
        raise ClientException(
            detail='the file was not uploaded', extra={'code': 'upload_missing'}
        )
    key: str | None = None
    try:
        if info.size != int(claims['s']):
            raise ClientException(
                detail='the uploaded size does not match the announced size',
                extra={'code': 'size_mismatch'},
            )
        _check_size(info.size, files_settings())
        if claims['x']:
            node, ctx = await access.load_node(
                session, scope, claims['n'], access.ITEM, 'update'
            )
            parent, name, existing, result = None, node.name, node, 'versioned'
        else:
            ctx = await access.load_drive(
                session, scope, claims['d'], access.ITEM, 'create'
            )
            parent = await nodes.get_folder(session, ctx.drive.id, claims['p'] or None)
            result, existing, name = await _resolve(
                session, scope, ctx, parent, claims['name'], claims['c']
            )
            if result == 'skipped':
                assert existing is not None
                return result, existing
        node_id = existing.id if existing else UUID(claims['n'])
        key = storage.version_key(ctx.drive.id, node_id, version_id)
        await store.copy(staging, key)
        node = await _add_version(
            session,
            scope,
            ctx,
            node=existing,
            parent=parent,
            name=name,
            node_id=node_id,
            version_id=version_id,
            key=key,
            size=info.size,
            mime=claims['m'],
            checksum=None,
            comment=comment,
        )
        return result, node  # type: ignore[return-value]
    except Exception:
        if key:
            await store.delete(key)
        raise
    finally:
        await store.delete(staging)


# --- versions -------------------------------------------------------------------------------------


async def list_versions(
    session: DBAsyncScopedSession, node: FileNode
) -> list[FileVersionOut]:
    rows = list(
        await session.scalars(
            select(FileVersion)
            .where(FileVersion.node_id == node.id)
            .order_by(FileVersion.number.desc())
        )
    )
    return await _version_outputs(session, node, rows)


async def _version_outputs(
    session: DBAsyncScopedSession, node: FileNode, rows: list[FileVersion]
) -> list[FileVersionOut]:
    names = await user_names(session, [r.uploaded_by for r in rows])
    return [
        FileVersionOut(
            id=str(v.id),
            number=v.number,
            size=v.size,
            mime=v.mime,
            checksum=v.checksum,
            comment=v.comment,
            scan_status=v.scan_status,
            restored_from=v.restored_from,
            uploaded_by=str(v.uploaded_by) if v.uploaded_by else None,
            uploaded_by_name=names.get(v.uploaded_by) if v.uploaded_by else None,
            current=v.id == node.current_version_id,
            created_at=v.created_at,
        )
        for v in rows
    ]


async def restore_version(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    version_id: str,
) -> FileNode:
    """The old version becomes a **new** current version (copied object; history kept, File-0301)."""
    source = await nodes.current_version(session, node, version_id)
    if source.id == node.current_version_id:
        raise ConflictException(
            detail='this is already the current version',
            extra={'code': 'already_current'},
        )
    new_id = uuid.uuid7()
    key = storage.version_key(node.drive_id, node.id, new_id)
    store = await storage.store_for(scope.tenant_id)
    await store.copy(source.key, key)
    try:
        return await _add_version(
            session,
            scope,
            ctx,
            node=node,
            parent=None,
            name=node.name,
            node_id=node.id,
            version_id=new_id,
            key=key,
            size=source.size,
            mime=source.mime,
            checksum=source.checksum,
            comment=None,
            restored_from=source.number,
        )
    except Exception:
        await store.delete(key)
        raise


async def comment_version(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    version_id: str,
    comment: str | None,
) -> FileVersionOut:
    version = await nodes.current_version(session, node, version_id)
    version.comment = (comment or '').strip()[:1000] or None
    record(
        session,
        scope,
        ctx.drive.id,
        'file.version_comment',
        node,
        version=version.number,
    )
    await session.flush()
    return (await _version_outputs(session, node, [version]))[0]


# --- download / preview ---------------------------------------------------------------------------


async def download(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    ctx: access.DriveCtx,
    node: FileNode,
    *,
    version_id: str | None = None,
    inline: bool = False,
) -> FileDownloadOut:
    """A 1–5 min signed URL after the permission check (Sto-0200); ``inline`` only for safe types (File-0206)."""
    if node.kind != 'file':
        raise ClientException(detail='folders cannot be downloaded')
    version = await nodes.current_version(session, node, version_id)
    if version.scan_status in BLOCKED_SCANS:
        raise ConflictException(
            detail=f'file not available: scan {version.scan_status}',
            extra={'code': f'scan_{version.scan_status}'},
        )
    show_inline = inline and inline_allowed(version.mime)
    url, exp = await storage.content_url(
        scope.tenant_id, version.key, version.mime, node.name, inline=show_inline
    )
    record(
        session,
        scope,
        ctx.drive.id,
        'file.previewed' if show_inline else 'file.downloaded',
        node,
        version=version.number,
    )
    await access.log_oversight(session, scope, ctx, 'download')
    return FileDownloadOut(
        url=url,
        filename=node.name,
        mime=version.mime,
        size=version.size,
        inline=show_inline,
        expires_at=storage.as_datetime(exp),
    )
