"""Checklist of a work item (work-model Ppm-0830…0834): ordered steps with an assignee, a due date and a
*mandatory* flag. Checking records who and when; the item's ``checklist_total`` / ``checklist_done`` (and its
progress in ``checklist`` mode) follow every change; an assigned step shows in its assignee's My Work (Ppm-0832);
a step can become a subtask (Ppm-0820). Events ``ppm.checklist_item.*`` (subject = the item)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import parse_uuid

from . import _events as events
from . import _work_items as items
from ._access import author

MAX_NAME = 500
MAX_ITEMS = 200
Item = ews_models.TaskChecklistItem
EDITABLE = ('name', 'assignee_user_id', 'due_date', 'is_mandatory')


def _name(value: str | None) -> str:
    name = (value or '').strip()
    if not name:
        raise ClientException(detail='a checklist step needs a text')
    if len(name) > MAX_NAME:
        raise ClientException(
            detail=f'a checklist step holds at most {MAX_NAME} characters'
        )
    return name


def _naive(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


async def listing(session: DBAsyncScopedSession, task_id: Any) -> list[Item]:
    rows = await session.scalars(
        select(Item)
        .where(Item.task_id == task_id)
        .order_by(Item.display_order, Item.created_at, Item.id)
    )
    return list(rows.all())


async def get(
    session: DBAsyncScopedSession, task: ews_models.Task, item_id: str
) -> Item:
    item = await session.scalar(
        select(Item).where(
            Item.id == parse_uuid(item_id, 'checklist item'), Item.task_id == task.id
        )
    )
    if item is None:
        raise NotFoundException(detail='checklist item not found')
    return item


async def _after(session: DBAsyncScopedSession, task: ews_models.Task) -> None:
    await items.refresh_checklist_counts(session, task)
    await items.refresh_rollups(session, task.parent_id)


def _data(task: ews_models.Task, item: Item) -> dict[str, Any]:
    return {
        'checklist_item_id': str(item.id),
        'name': item.name,
        'assignee': item.assignee_user_id,
        'due_date': item.due_date,
        'code': task.code,
        'task_name': task.name,
    }


async def add(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: ews_models.Task,
    *,
    name: str,
    assignee: str | None = None,
    due_date: datetime | None = None,
    mandatory: bool = False,
) -> Item:
    count = await session.scalar(
        select(func.count(Item.id)).where(Item.task_id == task.id)
    )
    if (count or 0) >= MAX_ITEMS:
        raise ClientException(
            detail=f'a checklist holds at most {MAX_ITEMS} steps',
            extra={'code': 'limit'},
        )
    last = await session.scalar(
        select(func.max(Item.display_order)).where(Item.task_id == task.id)
    )
    item = Item(
        task_id=task.id,
        tenant_id=task.tenant_id,
        name=_name(name),
        assignee_user_id=(assignee or '').strip() or None,
        due_date=_naive(due_date),
        is_mandatory=bool(mandatory),
        is_completed=False,
        display_order=int(last if last is not None and last >= 0 else -1) + 1,
    )
    session.add(item)
    await session.flush()
    await _after(session, task)
    await events.emit(
        session,
        scope,
        'ppm.checklist_item.created',
        'task',
        task.id,
        project_id=task.project_id,
        data=_data(task, item),
    )
    return item


async def change(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: ews_models.Task,
    item: Item,
    fields: dict[str, Any],
) -> Item:
    """Partial update: ``name``, ``assignee_user_id``, ``due_date``, ``is_mandatory``, ``is_completed``; ``clear``
    resets ``assignee_user_id`` / ``due_date``."""
    before = events.snapshot(item, (*EDITABLE, 'is_completed'))
    clear = set(fields.pop('clear', None) or []) & {'assignee_user_id', 'due_date'}
    if 'name' in fields:
        item.name = _name(fields['name'])
    if 'assignee_user_id' in fields:
        item.assignee_user_id = (fields['assignee_user_id'] or '').strip() or None
    if 'due_date' in fields:
        item.due_date = _naive(fields['due_date'])
    if 'is_mandatory' in fields:
        item.is_mandatory = bool(fields['is_mandatory'])
    for key in clear:
        setattr(item, key, None)
    completed_now = False
    if 'is_completed' in fields and bool(fields['is_completed']) != bool(
        item.is_completed
    ):
        item.is_completed = bool(fields['is_completed'])
        item.completed_at = (
            datetime.now(UTC).replace(tzinfo=None) if item.is_completed else None
        )
        item.completed_by = author(scope) if item.is_completed else None
        completed_now = item.is_completed
    await session.flush()
    await _after(session, task)
    changes = events.diff(before, events.snapshot(item, (*EDITABLE, 'is_completed')))
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.checklist_item.completed'
            if completed_now
            else 'ppm.checklist_item.updated',
            'task',
            task.id,
            project_id=task.project_id,
            changes=changes,
            data=_data(task, item),
        )
    return item


async def remove(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: ews_models.Task,
    item: Item,
) -> None:
    data = _data(task, item)
    await session.delete(item)
    await session.flush()
    await _after(session, task)
    await events.emit(
        session,
        scope,
        'ppm.checklist_item.deleted',
        'task',
        task.id,
        project_id=task.project_id,
        data=data,
    )


async def reorder(
    session: DBAsyncScopedSession, task: ews_models.Task, ids: list[str]
) -> list[Item]:
    """Order = the given ids (unknown ids → 400); steps left out keep their relative order after them."""
    current = await listing(session, task.id)
    by_id = {str(i.id): i for i in current}
    wanted = list(dict.fromkeys(ids))
    unknown = [i for i in wanted if i not in by_id]
    if unknown:
        raise ClientException(detail='unknown checklist steps: ' + ', '.join(unknown))
    ordered = [by_id[i] for i in wanted] + [
        i for i in current if str(i.id) not in set(wanted)
    ]
    for position, item in enumerate(ordered):
        item.display_order = position
    await session.flush()
    return ordered
