"""Activity of an item or a project (Ppm-0520): a read model over ``taas_ppm_audit_events`` (ADR-26), newest first,
paged by ``before`` (an ``occurred_at``), filtered by kind. Events whose subject is the item (field changes,
comments, checklist, time, attachments, assignments) form its Activity; a project's Activity is every event of the
project."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from db.models.ppm import PpmAuditEvent
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import ColumnElement, or_, select

KINDS: dict[str, tuple[str, ...]] = {
    'changes': (
        'ppm.task.updated',
        'ppm.project.updated',
        'ppm.task.parent_changed',
        'ppm.task.moved',
    ),
    'status': ('ppm.task.completed', 'ppm.task.reopened'),
    'comments': ('ppm.comment.',),
    'people': ('ppm.task.assigned', 'ppm.task.unassigned', 'ppm.project.member_'),
    'checklist': ('ppm.checklist_item.',),
    'time': ('ppm.time_entry.',),
    'files': ('ppm.attachment.', 'ppm.file.'),
    'lifecycle': (
        'ppm.task.created',
        'ppm.task.deleted',
        'ppm.project.created',
        'ppm.project.deleted',
    ),
}
"""Activity filter ``type`` → event topic prefixes."""


def _kind_filter(kind: str | None) -> ColumnElement[bool] | None:
    prefixes = KINDS.get(kind or '')
    if not prefixes:
        return None
    return or_(*(PpmAuditEvent.event.startswith(p) for p in prefixes))


async def listing(
    session: DBAsyncScopedSession,
    *,
    tenant_id: UUID,
    project_id: UUID | None = None,
    subject: tuple[str, str] | None = None,
    kind: str | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> list[PpmAuditEvent]:
    e = PpmAuditEvent
    query = select(e).where(e.tenant_id == tenant_id)
    if project_id is not None:
        query = query.where(e.project_id == project_id)
    if subject is not None:
        query = query.where(e.subject_type == subject[0], e.subject_id == subject[1])
    condition = _kind_filter(kind)
    if condition is not None:
        query = query.where(condition)
    if before is not None:
        query = query.where(e.occurred_at < before)
    rows = await session.scalars(
        query.order_by(e.occurred_at.desc(), e.id.desc()).limit(max(1, min(limit, 200)))
    )
    return list(rows.all())
