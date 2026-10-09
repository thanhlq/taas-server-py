"""Activity / audit log of drives and items (File-0307): one ``taas_file_activity`` row per change, download and
oversight access; rows outlive purged items (``node_id`` without FK, the name kept in ``detail``)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from db.models.files import FileActivity, FileNode
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import or_, select

from ews.security import RequestScope
from ews.shared import user_names, utcnow

from .schemas import FileActivityOut

ACTIONS = (
    'drive.created',
    'drive.updated',
    'drive.deleted',
    'drive.links_revoked',
    'member.granted',
    'member.revoked',
    'folder.created',
    'file.uploaded',
    'file.version',
    'file.version_restored',
    'file.version_comment',
    'file.copied',
    'file.downloaded',
    'file.previewed',
    'file.reprocessed',
    'node.renamed',
    'node.moved',
    'node.trashed',
    'node.restored',
    'node.purged',
    'admin.access',
)
"""Every ``action`` value (documented in taas-specs/files/files-api.md)."""


def record(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    drive_id: UUID,
    action: str,
    node: FileNode | None = None,
    *,
    tenant_id: UUID | None = None,
    **detail: Any,
) -> None:
    """Add an activity row (``scope`` = ``None``: the system, e.g. trash retention)."""
    if action not in ACTIONS:
        raise ValueError(f'unknown file activity {action!r}')
    if node is not None:
        detail.setdefault('name', node.name)
        detail.setdefault('kind', node.kind)
    session.add(
        FileActivity(
            tenant_id=scope.tenant_id if scope else tenant_id,
            drive_id=drive_id,
            node_id=node.id if node is not None else None,
            actor_id=scope.user_id if scope else None,
            action=action,
            detail={
                k: (str(v) if isinstance(v, UUID) else v) for k, v in detail.items()
            },
            created_at=utcnow(),
        )
    )


async def list_activity(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    drive_id: UUID,
    node: FileNode | None = None,
    limit: int = 100,
) -> list[FileActivityOut]:
    """Newest first; a folder's activity includes its subtree."""
    stmt = select(FileActivity).where(
        FileActivity.tenant_id == scope.tenant_id, FileActivity.drive_id == drive_id
    )
    if node is not None:
        if node.kind == 'folder':
            subtree = select(FileNode.id).where(
                FileNode.drive_id == drive_id, FileNode.path.like(f'{node.path}%')
            )
            stmt = stmt.where(
                or_(FileActivity.node_id == node.id, FileActivity.node_id.in_(subtree))
            )
        else:
            stmt = stmt.where(FileActivity.node_id == node.id)
    rows = list(
        await session.scalars(
            stmt.order_by(FileActivity.created_at.desc()).limit(min(max(limit, 1), 500))
        )
    )
    names = await user_names(session, [r.actor_id for r in rows])
    return [
        FileActivityOut(
            id=str(r.id),
            drive_id=str(r.drive_id),
            node_id=str(r.node_id) if r.node_id else None,
            actor_id=str(r.actor_id) if r.actor_id else None,
            actor_name=names.get(r.actor_id) if r.actor_id else None,
            action=r.action,
            detail=r.detail or {},
            created_at=r.created_at,
        )
        for r in rows
    ]
