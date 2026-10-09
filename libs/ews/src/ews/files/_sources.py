"""File sources (File-0100): drives whose access is decided by another app — ``kind = project`` (a project's files
and task attachments, File-0101). The owning app registers a resolver that returns the caller's implicit drive role
(``drive_manager`` · ``drive_editor`` · ``drive_viewer``) or ``None``; the File Manager then applies its usual rules
(404 / 403, uploads, versions, previews, signed delivery) — nothing is copied."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from db.models.files import FileDrive
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import select

from ews.security import RequestScope

from ._drives import _clean_drive_name, _ensure

SourceResolver = Callable[
    [DBAsyncScopedSession, RequestScope, FileDrive], Awaitable[str | None]
]
_SOURCES: dict[str, SourceResolver] = {}


def register_source(kind: str, resolver: SourceResolver) -> None:
    _SOURCES[kind] = resolver


def is_source(kind: str) -> bool:
    return kind in _SOURCES


async def source_role(
    session: DBAsyncScopedSession, scope: RequestScope, drive: FileDrive
) -> str | None:
    resolver = _SOURCES.get(drive.kind)
    return await resolver(session, scope, drive) if resolver is not None else None


async def ensure_source_drive(
    session: DBAsyncScopedSession,
    *,
    kind: str,
    tenant_id: UUID,
    organization_id: UUID,
    source_id: UUID,
    name: str,
) -> FileDrive:
    """The drive of a source object (created on first use, one per object)."""
    lookup = select(FileDrive).where(
        FileDrive.source_id == source_id,
        FileDrive.kind == kind,
        FileDrive.deleted_at.is_(None),
    )
    return await _ensure(
        session,
        {
            'tenant_id': tenant_id,
            'organization_id': organization_id,
            'kind': kind,
            'source_id': source_id,
            'name': _clean_drive_name(name)[:120],
            'settings': {},
        },
        ['source_id'],
        f"kind = '{kind}' AND deleted_at IS NULL",
        lookup,
    )


async def ensure_source_folder(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    drive: FileDrive,
    names: list[str],
):  # noqa: ANN201 — FileNode | None
    """The folder ``a/b`` of a source drive (created when missing), e.g. ``Tasks/TT-12``."""
    from ._access import DriveCtx
    from ._nodes import ensure_folders

    return await ensure_folders(session, scope, DriveCtx(drive, ''), None, names)
