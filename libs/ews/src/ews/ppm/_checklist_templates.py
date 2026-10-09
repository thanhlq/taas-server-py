"""Checklist templates (taas-specs/ppm/work-model/work-model-spec.md Ppm-0833): of the organization (``project_id``
null) or of a project; applying one **copies** its steps into an item's checklist (no live link); an item's checklist
can be saved as a template; an item type may apply a default template to its new items."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import or_, select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import parse_uuid, utcnow

from . import _checklists as checklists
from . import _events as events

CHECKLIST_TEMPLATE = EwsResources.CHECKLIST_TEMPLATE.value
Template = ews_models.ChecklistTemplate
TemplateItem = ews_models.ChecklistTemplateItem
MAX_ITEMS = 100


async def can_manage(scope: RequestScope, project_id: UUID | None) -> bool:
    if project_id is None:
        return await is_allowed(
            scope, CHECKLIST_TEMPLATE, 'manage', scope.org_domains()
        )
    from ._access import PROJECTS

    return await PROJECTS.allowed(scope, project_id, CHECKLIST_TEMPLATE, 'manage')


async def require_manage(scope: RequestScope, project_id: UUID | None) -> None:
    if not await can_manage(scope, project_id):
        raise PermissionDeniedException(
            detail=f'missing permission {CHECKLIST_TEMPLATE}:manage'
        )


async def listing(
    session: DBAsyncScopedSession, scope: RequestScope, project_id: UUID | None = None
) -> list[Any]:
    """Organization templates + (with ``project_id``) the project's own."""
    target = Template.project_id.is_(None)
    if project_id is not None:
        target = or_(Template.project_id.is_(None), Template.project_id == project_id)
    rows = await session.scalars(
        select(Template)
        .where(
            Template.organization_id == scope.organization_id,
            Template.deleted_at.is_(None),
            target,
        )
        .order_by(Template.project_id.nulls_first(), Template.name)
    )
    return list(rows.all())


async def get(
    session: DBAsyncScopedSession, scope: RequestScope, template_id: Any
) -> Any:
    row = await session.get(Template, parse_uuid(template_id, 'checklist template'))
    if (
        row is None
        or row.deleted_at is not None
        or row.organization_id != scope.organization_id
    ):
        raise NotFoundException(detail='checklist template not found')
    return row


def live_items(row: Any) -> list[Any]:
    return sorted(
        (i for i in row.items if i.deleted_at is None),
        key=lambda i: (i.display_order or 0, str(i.id)),
    )


def to_out(row: Any) -> dict[str, Any]:
    return {
        'id': str(row.id),
        'name': row.name or '',
        'description': row.description,
        'project_id': str(row.project_id) if row.project_id else None,
        'items': [
            {
                'name': i.name or '',
                'is_mandatory': bool(i.is_mandatory),
                'category': i.category,
            }
            for i in live_items(row)
        ],
    }


def _clean_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        name = str(item.get('name') or '').strip()[:500]
        if name:
            out.append(
                {
                    'name': name,
                    'is_mandatory': bool(item.get('is_mandatory')),
                    'category': item.get('category') or None,
                }
            )
    if len(out) > MAX_ITEMS:
        raise ClientException(
            detail=f'a template holds at most {MAX_ITEMS} steps',
            extra={'code': 'limit'},
        )
    return out


async def _replace_items(
    session: DBAsyncScopedSession, row: Any, items: list[dict[str, Any]]
) -> None:
    now = utcnow()
    for old in row.items:
        if old.deleted_at is None:
            old.deleted_at = now
    for i, item in enumerate(items):
        session.add(
            TemplateItem(
                template_id=row.id,
                name=item['name'],
                is_mandatory=item['is_mandatory'],
                category=item['category'],
                display_order=i,
            )
        )
    await session.flush()
    await session.refresh(row, ['items'])


async def create(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    name: str,
    description: str | None = None,
    project_id: UUID | None = None,
    items: list[dict[str, Any]] | None = None,
) -> Any:
    await require_manage(scope, project_id)
    name = (name or '').strip()[:200]
    if not name:
        raise ClientException(detail='a checklist template needs a name')
    cleaned = _clean_items(items or [])
    row = Template(
        name=name,
        description=description or None,
        project_id=project_id,
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        scope='task',
    )
    session.add(row)
    await session.flush()
    await session.refresh(row, ['items'])
    await _replace_items(session, row, cleaned)
    await events.emit(
        session,
        scope,
        'ppm.checklist_template.created',
        'checklist_template',
        row.id,
        project_id=project_id,
        data={'name': name},
    )
    return row


async def update(
    session: DBAsyncScopedSession, scope: RequestScope, row: Any, data: dict[str, Any]
) -> Any:
    await require_manage(scope, row.project_id)
    if 'name' in data:
        name = (data['name'] or '').strip()[:200]
        if not name:
            raise ClientException(detail='a checklist template needs a name')
        row.name = name
    if 'description' in data:
        row.description = data['description'] or None
    if data.get('items') is not None:
        await _replace_items(session, row, _clean_items(data['items']))
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.checklist_template.updated',
        'checklist_template',
        row.id,
        project_id=row.project_id,
        data={'name': row.name},
    )
    return row


async def remove(session: DBAsyncScopedSession, scope: RequestScope, row: Any) -> None:
    await require_manage(scope, row.project_id)
    row.deleted_at = utcnow()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.checklist_template.deleted',
        'checklist_template',
        row.id,
        project_id=row.project_id,
        data={'name': row.name},
    )


async def apply(
    session: DBAsyncScopedSession, scope: RequestScope, task: ews_models.Task, row: Any
) -> int:
    """Copy the template's steps after the item's current steps; returns how many were added."""
    if row.project_id is not None and row.project_id != task.project_id:
        raise ClientException(detail='this template belongs to another project')
    added = 0
    for item in live_items(row):
        await checklists.add(
            session,
            scope,
            task,
            name=item.name or '',
            mandatory=bool(item.is_mandatory),
        )
        added += 1
    return added


async def save_from_task(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: ews_models.Task,
    *,
    name: str,
    project_scope: bool,
) -> Any:
    """ "Save checklist as template" (organization, or the item's project)."""
    steps = await checklists.listing(session, task.id)
    if not steps:
        raise ClientException(detail='the checklist is empty')
    return await create(
        session,
        scope,
        name=name,
        project_id=task.project_id if project_scope else None,
        items=[{'name': s.name, 'is_mandatory': bool(s.is_mandatory)} for s in steps],
    )
