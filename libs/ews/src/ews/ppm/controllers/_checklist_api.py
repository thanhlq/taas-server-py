"""``/api/v1/tasks/{task_id}/checklist-items`` — the checklist of an item (Ppm-0830…0834): list, add, edit /
check, delete, reorder, convert a step into a subtask (Ppm-0820). Rules in ``ews.ppm._checklists``."""

from __future__ import annotations

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.security import current_scope

from .. import _access as access
from .. import _checklists as checklists
from .. import _work_items as items
from ..schemas._checklist_api import (
    PpmChecklistItemCreate,
    PpmChecklistItemOut,
    PpmChecklistItemUpdate,
    PpmChecklistOrder,
)
from ..schemas._task_api import TaskResponse
from ._task_support import task_to_response


def _out(item: ews_models.TaskChecklistItem) -> PpmChecklistItemOut:
    return PpmChecklistItemOut(
        id=str(item.id),
        task_id=str(item.task_id),
        name=item.name or '',
        is_completed=bool(item.is_completed),
        completed_at=item.completed_at,
        completed_by=item.completed_by,
        assignee_user_id=item.assignee_user_id,
        due_date=item.due_date,
        is_mandatory=bool(item.is_mandatory),
        position=max(0, item.display_order or 0),
    )


class TaskChecklistController(BaseController):
    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/{task_id}/checklist-items', summary='Checklist of an item, in order')
    @db_context_session
    async def list_items(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[PpmChecklistItemOut]:
        task, _ = await access.load_task(session, await current_scope(), task_id)
        return [_out(i) for i in await checklists.listing(session, task.id)]

    @post(
        '/{task_id}/checklist-items',
        status_code=status.HTTP_201_CREATED,
        summary='Add a step at the end',
    )
    @db_context_session(auto_commit=True)
    async def add_item(
        self, task_id: str, data: PpmChecklistItemCreate, session: DBAsyncScopedSession
    ) -> PpmChecklistItemOut:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        item = await checklists.add(
            session,
            scope,
            task,
            name=data.name,
            assignee=data.assignee_user_id,
            due_date=data.due_date,
            mandatory=data.is_mandatory,
        )
        await items.touch_project(session, project.id)
        return _out(item)

    @patch(
        '/{task_id}/checklist-items/{item_id}', summary='Edit, check / uncheck a step'
    )
    @db_context_session(auto_commit=True)
    async def update_item(
        self,
        task_id: str,
        item_id: str,
        data: PpmChecklistItemUpdate,
        session: DBAsyncScopedSession,
    ) -> PpmChecklistItemOut:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        item = await checklists.get(session, task, item_id)
        await checklists.change(session, scope, task, item, data.as_dict())
        await items.touch_project(session, project.id)
        return _out(item)

    @delete(
        '/{task_id}/checklist-items/{item_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def delete_item(
        self, task_id: str, item_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        await checklists.remove(
            session, scope, task, await checklists.get(session, task, item_id)
        )
        await items.touch_project(session, project.id)

    @put('/{task_id}/checklist-items/order', summary='Reorder the steps')
    @db_context_session(auto_commit=True)
    async def reorder(
        self, task_id: str, data: PpmChecklistOrder, session: DBAsyncScopedSession
    ) -> list[PpmChecklistItemOut]:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id, access.TASK, 'update')
        return [_out(i) for i in await checklists.reorder(session, task, data.ids)]

    @post(
        '/{task_id}/checklist-items/{item_id}/convert',
        status_code=status.HTTP_201_CREATED,
        summary='Turn a step into a subtask (text, assignee, due date kept)',
    )
    @db_context_session(auto_commit=True)
    async def convert(
        self, task_id: str, item_id: str, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'create'
        )
        item = await checklists.get(session, task, item_id)
        sub = await items.create_item(
            session,
            scope,
            project,
            items.NewItem(
                name=item.name or '',
                parent_id=task.id,
                owner=item.assignee_user_id,
                due_date=item.due_date,
                workflow_id=str(task.workflow_id) if task.workflow_id else None,
            ),
        )
        await checklists.remove(session, scope, task, item)
        collabs = await items.collaborators(session, [sub.id])
        return task_to_response(sub, collabs.get(sub.id))
