"""The single update path of an item — task page, quick view, bulk edits and automation actions (Ppm-1747: rules call
the same commands as the UI): fields, placement (workflow / stage / stage type), owner, remaining time, schedule
fields, custom fields, type change, stage-change rules, roll-ups, ``ppm.task.*`` events, project activity."""

from __future__ import annotations

from typing import Any, Optional

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException

from ews.security import RequestScope

from . import _access as access
from . import _comments as comments
from . import _custom_fields as custom_fields
from . import _item_types as item_types
from . import _recurrence as recurrence
from . import _schedule as schedule
from . import _time as time
from . import _work_items as items
from . import _workflow_service as wfs
from .controllers._task_support import apply_task_update
from .repos import RepoFactory, TaskRepository
from .schemas._task_api import PROGRESS_MODES


def check_progress_mode(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in PROGRESS_MODES:
        raise ClientException(
            detail=f'progress_mode must be one of {", ".join(sorted(PROGRESS_MODES))}'
        )
    return value


def clean_recurrence_rule(value: Optional[str]) -> Optional[str]:
    rule = recurrence.parse(value) if value else None
    return value.strip().removeprefix('RRULE:') if rule else None


async def update_item(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    t: ews_models.Task,
    project: ews_models.Project,
    fields: dict[str, Any],
) -> ews_models.Task:
    """Apply a ``TaskUpdateRequest``-shaped patch (``clear`` = fields to empty) as ``scope``; returns the item."""
    before = items.state(t)
    old_parent, old_stage, old_type = t.parent_id, t.stage_id, t.stage_type
    fields = dict(fields)
    cf_patch = fields.pop('custom_fields', None)
    if 'recurrence_rule' in fields:
        fields['recurrence_rule'] = clean_recurrence_rule(fields['recurrence_rule'])
    clear = set(fields.get('clear') or [])
    refs = await access.task_refs(
        session,
        project.id,
        task_list_id=fields.get('task_list_id'),
        iteration_id=fields.get('iteration_id'),
        parent_id=fields.get('parent_id'),
    )
    for key in ('task_list_id', 'iteration_id', 'parent_id'):
        if key in fields:
            fields[key] = refs[key]
    if 'parent_id' in fields:
        await items.check_parent(session, t, fields['parent_id'], project.id)
    if 'progress_mode' in fields:
        check_progress_mode(fields['progress_mode'])
    owner_change = 'user_id' in fields or 'user_id' in clear
    new_owner = fields.pop('user_id', None)
    workflow_id = fields.pop('workflow_id', None)
    stage_id = fields.pop('stage_id', None)
    stage_type = fields.pop('stage_type', None)
    if fields.get('work_item_type'):
        await item_types.check_key(
            session,
            project,
            wfs.ProjectProcess.of(project),
            fields['work_item_type'],
        )
    type_changed = (
        bool(fields.get('work_item_type'))
        and fields['work_item_type'] != t.work_item_type
    )
    if workflow_id or stage_id or stage_type:
        placement = await wfs.place_task(
            session,
            project,
            workflow_id=workflow_id,
            stage_id=stage_id,
            # Moving to another workflow keeps the task's lifecycle position.
            stage_type=stage_type or (t.stage_type if workflow_id else None),
            current_workflow_id=t.workflow_id,
        )
        if (
            stage_type
            and not stage_id
            and not workflow_id
            and placement.stage_type != stage_type
        ):
            # No stage of this type in the task's workflow: keep it where it is.
            placement = None
        if placement is not None:
            t.workflow_id = placement.workflow_id
            t.stage_id = placement.stage_id
            t.stage_type = placement.stage_type
    if 'remaining_minutes' in clear or fields.get('remaining_minutes') is not None:
        remaining = fields.pop('remaining_minutes', None)
        await time.set_remaining(
            session, scope, t, None if 'remaining_minutes' in clear else remaining
        )
        clear.discard('remaining_minutes')
    fields['clear'] = [c for c in clear if c != 'user_id']
    await schedule.check_item_fields(session, t, project, fields, clear)
    apply_task_update(t, fields)
    if t.parent_id is not None:
        t.phase_id = None  # subtasks are in their parent's phase
    await items.apply_type_change(session, project, t, type_changed)
    if t.recurrence_rule and not t.recurrence_id:
        t.is_recurrence, t.recurrence_id = True, str(t.id)
    cf_changes = (
        await custom_fields.set_values(session, scope, project, t, cf_patch)
        if cf_patch
        else {}
    )
    if owner_change:  # before the stage rules: they may need the new owner (Ppm-0202)
        await items.set_assignees(
            session,
            scope,
            t,
            owner=None if 'user_id' in clear else new_owner,
            collaborator_list=None,
        )
    if t.stage_id != old_stage:
        await items.on_stage_change(session, scope, t, old_stage, old_type)
    updated = await RepoFactory.get_repo(TaskRepository, session).update(t)
    await items.refresh_rollups(session, updated.id)
    if old_parent != updated.parent_id:
        await items.refresh_rollups(session, old_parent)
    await items.record_update(session, scope, updated, project, before, cf_changes)
    if updated.html_text and updated.html_text != before.get('html_text'):
        await comments.description_mentions(
            session, scope, project, updated, updated.html_text
        )
    await items.touch_project(session, updated.project_id)
    return updated
