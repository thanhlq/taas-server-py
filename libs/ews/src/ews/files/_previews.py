"""Thumbnails of listed items (File-0302, File-0500): one query for the current versions' ``thumb`` variants and
the drives' URL settings, then cached 24 h view URLs (``_delivery``) — lists never sign more than once per window."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from db.models.files import FileDrive, FileNode, FilePreview, FileVersion
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import and_, select

from . import _delivery as delivery

THUMB_MIME = 'image/webp'


@dataclass(slots=True)
class Thumb:
    status: str
    """``preview_status`` of the current version: ``pending`` · ``ready`` · ``none`` · ``failed``."""
    url: str | None = None
    placeholder: str | None = None


async def drive_settings(
    session: DBAsyncScopedSession, drive_ids: set[UUID]
) -> dict[UUID, dict[str, Any]]:
    if not drive_ids:
        return {}
    rows = await session.execute(
        select(FileDrive.id, FileDrive.settings).where(
            FileDrive.id.in_(list(drive_ids))
        )
    )
    return {r.id: r.settings or {} for r in rows}


async def thumbnails(
    session: DBAsyncScopedSession, tenant_id: UUID, nodes: Sequence[FileNode]
) -> dict[UUID, Thumb]:
    """``{node id: Thumb}`` for the files among ``nodes`` (folders and purged versions are left out)."""
    files = [n for n in nodes if n.kind == 'file' and n.current_version_id]
    if not files:
        return {}
    rows = await session.execute(
        select(
            FileVersion.id,
            FileVersion.preview_status,
            FilePreview.key,
            FilePreview.placeholder,
        )
        .outerjoin(
            FilePreview,
            and_(
                FilePreview.version_id == FileVersion.id, FilePreview.variant == 'thumb'
            ),
        )
        .where(FileVersion.id.in_([n.current_version_id for n in files]))
    )
    by_version = {r.id: r for r in rows}
    settings = await drive_settings(session, {n.drive_id for n in files})
    out: dict[UUID, Thumb] = {}
    for node in files:
        row = by_version.get(node.current_version_id)
        if row is None:
            continue
        thumb = Thumb(row.preview_status)
        if row.key:
            thumb.url, _ = await delivery.signed_url(
                tenant_id,
                settings.get(node.drive_id),
                node.id,
                row.key,
                THUMB_MIME,
                'thumbnail.webp',
                inline=True,
                view=True,
            )
            thumb.placeholder = row.placeholder
        out[node.id] = thumb
    return out
