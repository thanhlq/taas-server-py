"""The organization's item type library (taas-specs/ppm/work-model/work-model-spec.md Ppm-0802…0806): seeded on first
use from the universal template's types (catalog keys, default behaviours §5.1), custom types with new keys, archive /
restore, a behaviour that cannot change while items of the type exist (409 ``in_use``).

A project's process picks a subset (Ppm-0804): with a workflow template, the template's types plus the organization's
**custom** types; without one, any type of the library. Every item mirrors its type's behaviour (``taas_tasks.behaviour``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmItemType
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, PermissionDeniedException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, slugify

from . import _behaviours as behaviours
from . import _events as events
from . import _workflow_service as wfs
from . import workflow_catalog as catalog

ITEM_TYPE = EwsResources.ITEM_TYPE.value
EDITABLE = (
    'term',
    'translations',
    'group',
    'icon',
    'color',
    'description',
    'behaviour',
    'default_checklist_template_id',
)
GROUPS = (
    'work',
    'issues',
    'requests',
    'development',
    'communication',
    'domain',
    'process',
    'documentation',
)


async def can_manage(scope: RequestScope) -> bool:
    return await is_allowed(scope, ITEM_TYPE, 'manage', scope.org_domains())


async def require_manage(scope: RequestScope) -> None:
    if not await can_manage(scope):
        raise PermissionDeniedException(detail=f'missing permission {ITEM_TYPE}:manage')


def _catalog_types() -> list[dict[str, Any]]:
    """The universal template's types with their translations (``{locale: term}``)."""
    base = catalog.get_template(wfs.UNIVERSAL_TEMPLATE_ID, 'en') or {
        'work_item_types': []
    }
    out: list[dict[str, Any]] = []
    localized = {
        locale: {
            w['key']: w['term']
            for w in (
                catalog.get_template(wfs.UNIVERSAL_TEMPLATE_ID, locale) or {}
            ).get('work_item_types', [])
        }
        for locale in catalog.available_locales()
        if locale != 'en'
    }
    for i, w in enumerate(base['work_item_types']):
        translations = {
            loc: terms[w['key']]
            for loc, terms in localized.items()
            if terms.get(w['key']) and terms[w['key']] != w['term']
        }
        out.append({**w, 'position': float(i), 'translations': translations})
    return out


async def library(
    session: DBAsyncScopedSession,
    tenant_id: UUID,
    organization_id: UUID,
    *,
    include_archived: bool = False,
) -> list[PpmItemType]:
    """The organization's types in order (seeded from the catalog on first use)."""
    t = PpmItemType
    rows = list(
        (
            await session.scalars(
                select(t)
                .where(t.organization_id == organization_id)
                .order_by(t.position, t.term)
            )
        ).all()
    )
    if not rows:
        # concurrent first requests seed the same keys: the loser's rows are skipped
        await session.execute(
            pg_insert(PpmItemType).on_conflict_do_nothing(),
            [
                {
                    'tenant_id': tenant_id,
                    'organization_id': organization_id,
                    'key': w['key'],
                    'term': w['term'],
                    'translations': w['translations'],
                    'group': w.get('group') or 'work',
                    'icon': w.get('icon'),
                    'color': w.get('color'),
                    'behaviour': behaviours.default_for(w['key']),
                    'description': w.get('description'),
                    'origin': 'catalog',
                    'position': w['position'],
                }
                for w in _catalog_types()
            ],
        )
        rows = list(
            (
                await session.scalars(
                    select(t)
                    .where(t.organization_id == organization_id)
                    .order_by(t.position, t.term)
                )
            ).all()
        )
    return rows if include_archived else [r for r in rows if r.archived_at is None]


async def by_key(
    session: DBAsyncScopedSession, tenant_id: UUID, organization_id: UUID
) -> dict[str, PpmItemType]:
    return {r.key: r for r in await library(session, tenant_id, organization_id)}


async def behaviour_of(
    session: DBAsyncScopedSession, project: ews_models.Project, key: str | None
) -> str:
    """Behaviour of an item type key in the project's organization (library, else the default mapping)."""
    if not key:
        return behaviours.DEFAULT
    if project.organization_id is None or project.tenant_id is None:
        return behaviours.default_for(key)
    found = (await by_key(session, project.tenant_id, project.organization_id)).get(key)
    return found.behaviour if found else behaviours.default_for(key)


async def check_key(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    process: wfs.ProjectProcess,
    key: str | None,
) -> str | None:
    """Ppm-0804: a templated process accepts its own keys plus the organization's live custom types; an open process
    any library key (or a process key)."""
    if not key:
        return None
    if key in process.work_item_keys():
        return key
    lib = (
        await by_key(session, project.tenant_id, project.organization_id)
        if project.organization_id is not None and project.tenant_id is not None
        else {}
    )
    found = lib.get(key)
    if process.work_item_types_locked:
        if found is None or found.origin != 'custom':
            raise ClientException(
                detail=f"Work item type '{key}' is not part of the project's workflow template."
            )
        return key
    if lib and found is None:
        raise ClientException(detail=f"Unknown work item type '{key}'.")
    return key


async def items_of_type(
    session: DBAsyncScopedSession, organization_id: UUID, key: str
) -> int:
    task, project = ews_models.Task, ews_models.Project
    return int(
        await session.scalar(
            select(func.count(task.id))
            .join(project, project.id == task.project_id)
            .where(
                project.organization_id == organization_id,
                task.work_item_type == key,
                task.deleted_at.is_(None),
            )
        )
        or 0
    )


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k not in EDITABLE:
            continue
        if k == 'term':
            v = (v or '').strip()
            if not v:
                raise ClientException(detail='an item type needs a term')
            v = v[:200]
        elif k == 'behaviour' and not behaviours.is_behaviour(v):
            raise ClientException(detail=f'unknown behaviour {v!r}')
        elif k == 'group' and v not in GROUPS:
            v = 'domain'
        elif k == 'translations':
            v = {
                str(loc)[:10]: str(term).strip()[:200]
                for loc, term in (v or {}).items()
                if str(term).strip()
            }
        out[k] = v
    return out


def to_out(row: PpmItemType, used: int | None = None) -> dict[str, Any]:
    return {
        'id': str(row.id),
        'key': row.key,
        'term': row.term,
        'translations': row.translations or {},
        'group': row.group,
        'icon': row.icon,
        'color': row.color,
        'behaviour': row.behaviour,
        'description': row.description,
        'default_checklist_template_id': str(row.default_checklist_template_id)
        if row.default_checklist_template_id
        else None,
        'origin': row.origin,
        'archived': row.archived_at is not None,
        'used': used,
    }


async def create(
    session: DBAsyncScopedSession, scope: RequestScope, data: dict[str, Any]
) -> PpmItemType:
    await require_manage(scope)
    fields = _clean({**data, 'behaviour': data.get('behaviour') or behaviours.DEFAULT})
    if 'term' not in fields:
        raise ClientException(detail='an item type needs a term')
    lib = await library(
        session, scope.tenant_id, scope.organization_id, include_archived=True
    )
    base = slugify(fields['term'], 56).replace('-', '_') or 'type'
    taken = {r.key for r in lib if r.archived_at is None}
    key, n = base, 2
    while key in taken:
        key, n = f'{base}_{n}', n + 1
    row = PpmItemType(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        key=key,
        origin='custom',
        position=max((r.position for r in lib), default=0.0) + 1,
        **{'group': 'domain', **fields},
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.item_type.created',
        'item_type',
        row.id,
        data={'key': key, 'behaviour': row.behaviour},
    )
    return row


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    row: PpmItemType,
    data: dict[str, Any],
) -> PpmItemType:
    await require_manage(scope)
    fields = _clean(data)
    if 'behaviour' in fields and fields['behaviour'] != row.behaviour:
        used = await items_of_type(session, row.organization_id, row.key)
        if used:
            raise ConflictException(
                detail=f'{used} items use this type: archive it and create a new one to change the behaviour',
                extra={'code': 'in_use', 'count': used},
            )
    before = {k: getattr(row, k) for k in fields}
    for k, v in fields.items():
        setattr(row, k, v)
    await session.flush()
    changes = events.diff(
        {k: events.json_value(v) for k, v in before.items()},
        {k: events.json_value(getattr(row, k)) for k in fields},
    )
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.item_type.updated',
            'item_type',
            row.id,
            changes=changes,
            data={'key': row.key},
        )
    return row


async def set_archived(
    session: DBAsyncScopedSession, scope: RequestScope, row: PpmItemType, archived: bool
) -> PpmItemType:
    await require_manage(scope)
    if archived and row.archived_at is None:
        row.archived_at = datetime.now(UTC)
        topic = 'ppm.item_type.archived'
    elif not archived and row.archived_at is not None:
        clash = await session.scalar(
            select(PpmItemType.id).where(
                PpmItemType.organization_id == row.organization_id,
                PpmItemType.key == row.key,
                PpmItemType.archived_at.is_(None),
                PpmItemType.id != row.id,
            )
        )
        if clash:
            raise ConflictException(
                detail='a live type uses this key', extra={'code': 'key_taken'}
            )
        row.archived_at = None
        topic = 'ppm.item_type.restored'
    else:
        return row
    await session.flush()
    await events.emit(session, scope, topic, 'item_type', row.id, data={'key': row.key})
    return row


async def get(
    session: DBAsyncScopedSession, scope: RequestScope, item_type_id: Any
) -> PpmItemType:
    from ews.shared import parse_uuid

    row = await session.get(PpmItemType, parse_uuid(item_type_id, 'item type'))
    if row is None or row.organization_id != scope.organization_id:
        from foundation.exceptions import NotFoundException

        raise NotFoundException(detail='item type not found')
    return row
