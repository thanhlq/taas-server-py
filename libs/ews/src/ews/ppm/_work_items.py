"""Work item rules (taas-specs/ppm/work-model/work-model-spec.md): subtask hierarchy (Ppm-0815…0818), roll-ups
(§5.2), complete / reopen (Ppm-0807), owner + collaborators (Ppm-0825…0827) and the item events (Ppm-0008).

- Hierarchy: ``parent_id`` in the same project, ≤ 3 levels (item → subtask → sub-subtask), no cycle.
- Roll-ups are recalculated in the transaction of every change that affects them, up to the root: counted
  children, done children, progress (``progress_mode``: ``None`` = from subtasks when there are some, ``checklist``,
  ``manual``), roll-up dates.
- Done = a *done*-band stage that counts in progress, or ``completed_at`` (ADR-3). Entering such a stage sets
  ``completed_at`` / ``completed_by`` and remembers ``previous_stage_id``; leaving it clears them. Mandatory
  checklist items block it (409 ``checklist_incomplete``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, or_, select, update

from ews.security import RequestScope
from ews.shared import ConflictException, html_to_text, sanitize_html

from . import _behaviours as behaviours
from . import _events as events
from . import _item_types as item_types
from . import _workflow_rules as stage_rules
from . import _workflow_service as wfs
from . import workflow_catalog as catalog
from ._access import author, task_refs
from ._description import check_description, description_text
from .controllers._task_support import (
    clamp_priority,
    clean_list,
    next_task_code,
    task_labels,
    task_watchers,
)

MAX_LEVELS = 3
TRACKED = (
    'name',
    'description',
    'html_text',
    'workflow_id',
    'stage_id',
    'stage_type',
    'work_item_type',
    'priority',
    'start_date',
    'due_date',
    'estimated_minutes',
    'progress',
    'progress_mode',
    'user_id',
    'task_list_id',
    'iteration_id',
    'parent_id',
    'requested_user_id',
    'completed_at',
    'behaviour',
    'recurrence_rule',
    'phase_id',
    'duration_days',
    'schedule_mode',
    'constraint_type',
    'constraint_date',
    'remaining_minutes',
)

Task = ews_models.Task


def now() -> datetime:
    """Naive UTC (the task timestamps are plain ``TIMESTAMP`` columns)."""
    return datetime.now(UTC).replace(tzinfo=None)


def state(t: Task) -> dict[str, Any]:
    """The tracked fields of an item (for ``changes``)."""
    out = events.snapshot(t, TRACKED)
    out['labels'] = task_labels(t)
    out['watchers'] = task_watchers(t)
    return out


def counts_in_progress(stage_type: str | None, behaviour: str | None = None) -> bool:
    """Counted in progress: not in a cancelled / rejected stage and of a behaviour that counts (§5.1)."""
    return (
        stage_type is None or stage_type not in catalog.excluded_stage_types()
    ) and behaviours.counts(behaviour)


def is_done_type(stage_type: str | None) -> bool:
    return stage_type in catalog.done_stage_types() and counts_in_progress(stage_type)


def is_done(t: Task) -> bool:
    return is_done_type(t.stage_type) or (
        t.completed_at is not None and counts_in_progress(t.stage_type)
    )


# --- hierarchy ------------------------------------------------------------------------------------


def _error(detail: str, code: str) -> ClientException:
    return ClientException(detail=detail, extra={'code': code})


async def ancestors(session: DBAsyncScopedSession, task_id: UUID | None) -> list[UUID]:
    """Ids of the parent chain of ``task_id`` (closest first), ``task_id`` excluded."""
    out: list[UUID] = []
    current = task_id
    for _ in range(MAX_LEVELS + 5):
        if current is None:
            break
        parent = await session.scalar(select(Task.parent_id).where(Task.id == current))
        if parent is None or parent in out:
            break
        out.append(parent)
        current = parent
    return out


async def subtree_ids(session: DBAsyncScopedSession, task_id: UUID) -> list[list[UUID]]:
    """Live descendants by level: ``[[children], [grandchildren], …]``."""
    levels: list[list[UUID]] = []
    frontier = [task_id]
    seen = {task_id}
    for _ in range(MAX_LEVELS + 5):
        rows = await session.scalars(
            select(Task.id).where(
                Task.parent_id.in_(frontier), Task.deleted_at.is_(None)
            )
        )
        nxt = [i for i in rows.all() if i not in seen]
        if not nxt:
            break
        seen.update(nxt)
        levels.append(nxt)
        frontier = nxt
    return levels


async def check_parent(
    session: DBAsyncScopedSession,
    task: Task | None,
    parent_id: UUID | None,
    project_id: UUID,
) -> None:
    """400 ``hierarchy_project`` · ``hierarchy_cycle`` · ``hierarchy_depth`` (Ppm-0815)."""
    if parent_id is None:
        return
    parent = await session.scalar(
        select(Task).where(Task.id == parent_id, Task.deleted_at.is_(None))
    )
    if parent is None or parent.project_id != project_id:
        raise _error('the parent item must be in the same project', 'hierarchy_project')
    chain = [parent_id, *await ancestors(session, parent_id)]
    height = 0
    if task is not None:
        if task.id in chain:
            raise _error(
                'an item cannot be under itself or one of its subtasks',
                'hierarchy_cycle',
            )
        height = len(await subtree_ids(session, task.id))
    # level of the moved item = len(chain) + 1; its deepest descendant = that + height
    if len(chain) + 1 + height > MAX_LEVELS:
        raise _error(f'items nest at most {MAX_LEVELS} levels deep', 'hierarchy_depth')


# --- roll-ups -------------------------------------------------------------------------------------


def _half_even(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


async def refresh_rollups(session: DBAsyncScopedSession, task_id: UUID | None) -> None:
    """Recalculate the roll-ups of ``task_id`` and of every ancestor (§5.2)."""
    current = task_id
    for _ in range(MAX_LEVELS + 5):
        if current is None:
            return
        parent = await session.get(Task, current)
        if parent is None:
            return
        children = list(
            (
                await session.scalars(
                    select(Task).where(
                        Task.parent_id == parent.id, Task.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        counted = [c for c in children if counts_in_progress(c.stage_type, c.behaviour)]
        parent.child_count = len(counted)
        parent.done_child_count = sum(1 for c in counted if is_done(c))
        dated_start = [
            d
            for c in children
            for d in (c.rollup_start_date or c.start_date,)
            if d is not None
        ]
        dated_due = [
            d
            for c in children
            for d in (c.rollup_due_date or c.due_date,)
            if d is not None
        ]
        parent.rollup_start_date = min(dated_start) if dated_start else None
        parent.rollup_due_date = max(dated_due) if dated_due else None
        if parent.progress_mode is None and counted:
            weights = (
                [Decimal(c.estimated_minutes) for c in counted]
                if all((c.estimated_minutes or 0) > 0 for c in counted)
                else [Decimal(1)] * len(counted)
            )
            values = [
                Decimal(100 if is_done(c) else max(0, min(100, c.progress or 0)))
                for c in counted
            ]
            total = sum(weights) or Decimal(1)
            parent.progress = _half_even(
                sum(w * v for w, v in zip(weights, values, strict=True)) / total
            )
        elif parent.progress_mode == 'checklist' and parent.checklist_total:
            parent.progress = _half_even(
                Decimal(100 * parent.checklist_done) / Decimal(parent.checklist_total)
            )
        await session.flush()
        current = parent.parent_id


async def refresh_checklist_counts(session: DBAsyncScopedSession, task: Task) -> None:
    item = ews_models.TaskChecklistItem
    total, done = (
        await session.execute(
            select(
                func.count(item.id),
                func.count(item.id).filter(item.is_completed.is_(True)),
            ).where(item.task_id == task.id)
        )
    ).one()
    task.checklist_total, task.checklist_done = int(total), int(done)
    if task.progress_mode == 'checklist' and task.checklist_total:
        task.progress = _half_even(
            Decimal(100 * task.checklist_done) / Decimal(task.checklist_total)
        )
    await session.flush()


# --- completion -----------------------------------------------------------------------------------


async def open_mandatory_items(
    session: DBAsyncScopedSession, task_id: UUID
) -> list[str]:
    item = ews_models.TaskChecklistItem
    rows = await session.scalars(
        select(item.name).where(
            item.task_id == task_id,
            item.is_mandatory.is_(True),
            or_(item.is_completed.is_(None), item.is_completed.is_(False)),
        )
    )
    return [n or '' for n in rows.all()]


@dataclass(frozen=True, slots=True)
class DoneBlock:
    """Why an item cannot be done yet (409 ``code``)."""

    code: str
    detail: str
    extra: dict[str, Any]


DoneGuard = Callable[[DBAsyncScopedSession, Task], Awaitable[DoneBlock | None]]
_done_guards: list[DoneGuard] = []


def register_done_guard(guard: DoneGuard) -> DoneGuard:
    """A rule that can refuse entering the done band (approvals pending, required fields — Ppm-0807); decorator."""
    if guard not in _done_guards:
        _done_guards.append(guard)
    return guard


async def check_can_finish(session: DBAsyncScopedSession, task: Task) -> None:
    """409 when a mandatory checklist item is open (``checklist_incomplete``) or a registered guard refuses."""
    missing = await open_mandatory_items(session, task.id)
    if missing:
        raise ConflictException(
            detail='finish the mandatory checklist items first',
            extra={'code': 'checklist_incomplete', 'items': missing},
        )
    for guard in _done_guards:
        block = await guard(session, task)
        if block is not None:
            raise ConflictException(
                detail=block.detail, extra={'code': block.code, **block.extra}
            )


async def done_stage(
    session: DBAsyncScopedSession,
    workflow_id: UUID | None,
    current_stage_id: UUID | None = None,
) -> ews_models.WorkflowStage | None:
    """The first done-band stage of the workflow — the first one the current stage allows (Ppm-0201)."""
    if workflow_id is None:
        return None
    stages = (await wfs.load_stages(session, [workflow_id])).get(workflow_id) or []
    done = [s for s in stages if is_done_type(s.stage_type)]
    current = next((s for s in stages if s.id == current_stage_id), None)
    return stage_rules.first_allowed(current, done) or (done[0] if done else None)


async def on_stage_change(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: Task,
    old_stage_id: UUID | None,
    old_type: str | None,
    *,
    rules: bool = True,
) -> None:
    """Keep ``completed_at`` / ``previous_stage_id`` in step with the done band (call after a placement change).

    With ``rules`` (every move but *reopen*): the old stage's allowed next stages (Ppm-0201), the new stage's default
    assignee (Ppm-0203) and entry requirements (Ppm-0202)."""
    if rules and task.stage_id is not None and task.stage_id != old_stage_id:
        new_stage = await session.get(ews_models.WorkflowStage, task.stage_id)
        if new_stage is not None:
            old_stage = (
                await session.get(ews_models.WorkflowStage, old_stage_id)
                if old_stage_id
                else None
            )
            stage_rules.check_transition(old_stage, new_stage)
            owner = stage_rules.default_assignee(new_stage)
            if owner and not task.user_id:
                await set_assignees(
                    session, scope, task, owner=owner, collaborator_list=None
                )
            stage_rules.check_requirements(task, new_stage)
    was, now_done = is_done_type(old_type), is_done_type(task.stage_type)
    if now_done and not was:
        await check_can_finish(session, task)
        task.previous_stage_id = old_stage_id
        task.completed_at = now()
        task.completed_by = author(scope)
    elif was and not now_done:
        task.completed_at = None
        task.completed_by = None


async def complete(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: Task,
    project: ews_models.Project,
    *,
    cascade: bool = False,
) -> list[Task]:
    """Move to the first done-band stage of its workflow (Ppm-0807); open subtasks → 409 ``open_subtasks`` unless
    ``cascade``. Returns every completed item."""
    if is_done(task):
        return []
    open_children = [
        c
        for c in (
            await session.scalars(
                select(Task).where(Task.parent_id == task.id, Task.deleted_at.is_(None))
            )
        ).all()
        if counts_in_progress(c.stage_type, c.behaviour) and not is_done(c)
    ]
    if open_children and not cascade:
        raise ConflictException(
            detail=f'{len(open_children)} open subtasks: complete them too?',
            extra={'code': 'open_subtasks', 'count': len(open_children)},
        )
    completed: list[Task] = []
    for child in open_children:
        completed += await complete(session, scope, child, project, cascade=True)
    target = await done_stage(session, task.workflow_id, task.stage_id)
    before = state(task)
    old_stage, old_type = task.stage_id, task.stage_type
    if target is not None:
        task.stage_id, task.stage_type = target.id, target.stage_type
    await on_stage_change(session, scope, task, old_stage, old_type)
    if target is None:  # a workflow without a done stage: completion date only
        await check_can_finish(session, task)
        task.previous_stage_id = old_stage
        task.completed_at = now()
        task.completed_by = author(scope)
    await session.flush()
    await refresh_rollups(session, task.parent_id)
    await record_update(session, scope, task, project, before)
    completed.append(task)
    return completed


async def reopen(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: Task,
    project: ews_models.Project,
) -> None:
    """Back to ``previous_stage_id`` (same workflow, still live), else the workflow's default stage."""
    if not is_done(task):
        return
    stages = (
        (await wfs.load_stages(session, [task.workflow_id])).get(task.workflow_id)
        if task.workflow_id
        else []
    )
    stages = stages or []
    target = next(
        (
            s
            for s in stages
            if s.id == task.previous_stage_id and not is_done_type(s.stage_type)
        ),
        None,
    )
    target = target or next(
        (s for s in stages if not is_done_type(s.stage_type) and s.is_default), None
    )
    target = target or next((s for s in stages if not is_done_type(s.stage_type)), None)
    before = state(task)
    if target is not None:
        task.stage_id, task.stage_type = target.id, target.stage_type
    task.completed_at = None
    task.completed_by = None
    await session.flush()
    await refresh_rollups(session, task.parent_id)
    await record_update(session, scope, task, project, before)


# --- assignees ------------------------------------------------------------------------------------


async def collaborators(
    session: DBAsyncScopedSession, task_ids: list[UUID]
) -> dict[UUID, list[str]]:
    if not task_ids:
        return {}
    tu = ews_models.TaskUser
    rows = await session.execute(
        select(tu.task_id, tu.user_id)
        .where(
            tu.task_id.in_(task_ids), tu.deleted_at.is_(None), tu.role == 'collaborator'
        )
        .order_by(tu.created_at, tu.id)
    )
    out: dict[UUID, list[str]] = {}
    for task_id, user in rows.all():
        if user:
            out.setdefault(task_id, []).append(user)
    return out


def _clean_user(value: str | None) -> str | None:
    value = (value or '').strip()
    return value or None


async def set_assignees(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: Task,
    *,
    owner: str | None,
    collaborator_list: list[str] | None,
) -> None:
    """Owner (≤ 1, mirrored in ``user_id``) + collaborators (Ppm-0825, Ppm-0827).

    - ``collaborator_list`` given (``PUT …/assignees``): exactly these collaborators.
    - ``None`` (owner change only, e.g. ``PATCH user_id``): a collaborator made owner turns the previous owner into a
      collaborator; another owner replaces the previous one; the other collaborators stay.

    Every new assignee becomes a watcher; ``ppm.task.assigned`` / ``unassigned`` per change."""
    tu = ews_models.TaskUser
    owner = _clean_user(owner)
    rows = (
        await session.scalars(
            select(tu).where(tu.task_id == task.id, tu.deleted_at.is_(None))
        )
    ).all()
    current = {r.user_id: r for r in rows if r.user_id}
    if (
        task.user_id and task.user_id not in current
    ):  # owner set before the assignee table was used
        current_roles = {
            task.user_id: 'owner',
            **{u: r.role for u, r in current.items()},
        }
    else:
        current_roles = {u: r.role for u, r in current.items()}
    if collaborator_list is not None:
        collabs = [
            u
            for u in dict.fromkeys(_clean_user(c) for c in collaborator_list)
            if u and u != owner
        ]
    else:
        collabs = [
            u
            for u, role in current_roles.items()
            if role == 'collaborator' and u != owner
        ]
        previous = task.user_id
        if (
            previous
            and owner
            and previous != owner
            and current_roles.get(owner) == 'collaborator'
        ):
            collabs.append(previous)
    wanted = {
        **dict.fromkeys(collabs, 'collaborator'),
        **({owner: 'owner'} if owner else {}),
    }
    stamp = datetime.now(UTC)
    for user, row in current.items():
        if user not in wanted:
            row.deleted_at = stamp
        elif row.role != wanted[user]:
            row.role = wanted[user]
    for user, role in wanted.items():
        if user not in current:
            session.add(
                tu(
                    task_id=task.id,
                    user_id=user,
                    role=role,
                    tenant_id=task.tenant_id,
                    created_by=author(scope),
                )
            )
    task.user_id = owner
    watchers = task_watchers(task)
    watchers += [u for u in wanted if u not in watchers]
    task.followers = {
        **(task.followers if isinstance(task.followers, dict) else {}),
        'users': watchers,
    }
    await session.flush()
    base = {'code': task.code, 'name': task.name}
    for user, role in wanted.items():
        if current_roles.get(user) != role:
            await events.emit(
                session,
                scope,
                'ppm.task.assigned',
                'task',
                task.id,
                project_id=task.project_id,
                data={**base, 'user': user, 'role': role},
            )
    for user in current_roles:
        if user not in wanted:
            await events.emit(
                session,
                scope,
                'ppm.task.unassigned',
                'task',
                task.id,
                project_id=task.project_id,
                data={**base, 'user': user},
            )


# --- events ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class Recorded:
    changes: events.Changes


async def record_update(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    task: Task,
    project: ews_models.Project,
    before: dict[str, Any],
    extra: events.Changes | None = None,
) -> Recorded:
    """``ppm.task.updated`` with the changed fields (+ ``extra``, e.g. ``cf_<key>`` values) and the semantic events
    (completed · reopened · parent_changed)."""
    changes = {**events.diff(before, state(task)), **(extra or {})}
    if not changes:
        return Recorded({})
    base = {'code': task.code, 'name': task.name}
    await events.emit(
        session,
        scope,
        'ppm.task.updated',
        'task',
        task.id,
        project_id=project.id,
        changes=changes,
        data=base,
    )
    if 'completed_at' in changes:
        topic = 'ppm.task.completed' if task.completed_at else 'ppm.task.reopened'
        await events.emit(
            session,
            scope,
            topic,
            'task',
            task.id,
            project_id=project.id,
            data={**base, 'stage_id': task.stage_id},
        )
    if 'parent_id' in changes:
        await events.emit(
            session,
            scope,
            'ppm.task.parent_changed',
            'task',
            task.id,
            project_id=project.id,
            changes={'parent_id': changes['parent_id']},
            data=base,
        )
    return Recorded(changes)


async def delete_subtree(session: DBAsyncScopedSession, task: Task) -> list[UUID]:
    """Soft-delete the item's descendants (Ppm-0818); returns their ids."""
    ids = [i for level in await subtree_ids(session, task.id) for i in level]
    if ids:
        await session.execute(
            update(Task).where(Task.id.in_(ids)).values(deleted_at=datetime.now(UTC))
        )
    return ids


# --- create ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class NewItem:
    """What a new work item needs; ids as sent by clients (checked against the project)."""

    name: str
    description: str | None = None
    description_html: str | None = None
    description_doc: dict[str, Any] | None = None
    workflow_id: str | None = None
    stage_id: str | None = None
    stage_type: str | None = None
    work_item_type: str | None = None
    parent_id: Any = None
    requested_user_id: str | None = None
    owner: str | None = None
    collaborators: list[str] | None = None
    task_list_id: Any = None
    iteration_id: Any = None
    labels: list[str] | None = None
    priority: int | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    estimated_minutes: int | None = None
    progress: int | None = None
    progress_mode: str | None = None
    recurrence_rule: str | None = None
    recurrence_id: str | None = None
    created_from_template_item_id: UUID | None = None
    schedule: dict[str, Any] | None = None
    """``phase_id`` · ``duration_days`` · ``schedule_mode`` · ``constraint_type`` · ``constraint_date`` (checked by
    ``_schedule.check_item_fields``)."""
    cause: str | None = None
    """``template`` · ``recurrence`` · ``quick_add`` · ``automation`` (event ``cause``)."""


async def touch_project(session: DBAsyncScopedSession, project_id: UUID | None) -> None:
    """Record activity on a project (Ppm-0007)."""
    if project_id is None:
        return
    await session.execute(
        update(ews_models.Project)
        .where(ews_models.Project.id == project_id)
        .values(last_activity_at=now())
    )


async def create_item(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    new: NewItem,
) -> Task:
    """One work item in the project: placement (stage / type / default), code, hierarchy check, owner +
    collaborators, roll-ups, description mentions and ``ppm.task.created`` — the single create path of the task
    API, quick add, checklist conversion, intake and templates."""
    from . import (
        _comments as comments,
    )  # comments → members → access: imported late (no cycle at import)

    name = (new.name or '').strip()
    if not name:
        raise ClientException(detail='an item needs a name')
    refs = await task_refs(
        session,
        project.id,
        parent_id=new.parent_id,
        task_list_id=new.task_list_id,
        iteration_id=new.iteration_id,
    )
    await check_parent(session, None, refs['parent_id'], project.id)
    process = wfs.ProjectProcess.of(project)
    placement = await wfs.place_task(
        session,
        project,
        workflow_id=new.workflow_id,
        stage_id=new.stage_id,
        stage_type=new.stage_type,
    )
    work_item_type = (
        await item_types.check_key(session, project, process, new.work_item_type)
        or process.default_work_item_type()
    )
    behaviour = await item_types.behaviour_of(session, project, work_item_type)
    dated = behaviours.apply_rules(
        behaviour,
        {
            'start_date': new.start_date,
            'due_date': new.due_date,
            'estimated_minutes': new.estimated_minutes,
        },
    )
    sequence_id, code = await next_task_code(session, project.id)
    html = sanitize_html(new.description_html) if new.description_html else ''
    doc = check_description(new.description_doc) if new.description_doc else None
    task = Task(
        project_id=project.id,
        tenant_id=project.tenant_id,
        name=name,
        description=new.description
        or (description_text(doc) if doc else None)
        or (html_to_text(html) if html else None),
        description_doc=doc,
        html_text=html or None,
        content_type='html' if html else None,
        code=code,
        sequence_id=sequence_id,
        workflow_id=placement.workflow_id,
        stage_id=placement.stage_id,
        stage_type=placement.stage_type,
        work_item_type=work_item_type,
        behaviour=behaviour,
        recurrence_rule=new.recurrence_rule,
        created_from_template_item_id=new.created_from_template_item_id,
        parent_id=refs['parent_id'],
        requested_user_id=new.requested_user_id,
        task_list_id=refs['task_list_id'],
        iteration_id=refs['iteration_id'],
        tags={'labels': clean_list(new.labels)} if new.labels else None,
        priority=clamp_priority(new.priority),
        start_date=dated['start_date'],
        due_date=dated['due_date'],
        estimated_minutes=dated['estimated_minutes'],
        progress=new.progress or 0,
        progress_mode=new.progress_mode,
        child_count=0,
        done_child_count=0,
        checklist_total=0,
        checklist_done=0,
    )
    session.add(task)
    await session.flush()
    if task.recurrence_rule:
        task.is_recurrence = True
        task.recurrence_id = new.recurrence_id or str(task.id)
    if is_done_type(task.stage_type):
        task.completed_at = now()
        task.completed_by = author(scope)
    if new.schedule:
        from . import _schedule as schedule  # schedule → work items: imported late

        fields = dict(new.schedule)
        await schedule.check_item_fields(session, task, project, fields, set())
        for key, value in fields.items():
            setattr(task, key, value)
        await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.task.created',
        'task',
        task.id,
        project_id=project.id,
        data={
            'code': task.code,
            'name': task.name,
            'item_type': task.work_item_type,
            'behaviour': task.behaviour,
            'parent_id': task.parent_id,
            'stage_id': task.stage_id,
        },
        cause=new.cause,
    )
    if new.owner or new.collaborators:
        await set_assignees(
            session,
            scope,
            task,
            owner=new.owner,
            collaborator_list=new.collaborators or [],
        )
    await refresh_rollups(session, task.parent_id)
    if html:
        await comments.description_mentions(session, scope, project, task, html)
    await touch_project(session, project.id)
    return task


async def apply_type_change(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    task: Task,
    type_changed: bool,
) -> None:
    """Mirror the behaviour of the item's type (Ppm-0806) and apply its rules (a milestone: one date, no estimate)."""
    if type_changed or task.behaviour is None:
        task.behaviour = await item_types.behaviour_of(
            session, project, task.work_item_type
        )
    dated = behaviours.apply_rules(
        task.behaviour,
        {
            'start_date': task.start_date,
            'due_date': task.due_date,
            'estimated_minutes': task.estimated_minutes,
        },
    )
    task.start_date, task.due_date, task.estimated_minutes = (
        dated['start_date'],
        dated['due_date'],
        dated['estimated_minutes'],
    )


async def move_item(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: Task,
    source: ews_models.Project,
    target: ews_models.Project,
) -> list[Task]:
    """Move an item with its subtree, checklist, comments, time and links to another project of the organization
    (Ppm-0808): new codes in the target (the old one kept as an alias in ``properties.former_codes``), placement by
    stage type in the target's default workflow, top level in the target. Files stay in the source project's drive."""
    if target.id == source.id:
        raise ClientException(detail='the item is already in this project')
    if target.organization_id != source.organization_id or target.kind == 'template':
        raise ClientException(
            detail='items move only between projects of the same organization'
        )
    ids = [
        task.id,
        *(i for level in await subtree_ids(session, task.id) for i in level),
    ]
    moved: list[Task] = []
    old_parent = task.parent_id
    for item_id in ids:
        item = await session.get(Task, item_id)
        if item is None:
            continue
        before_code = item.code
        placement = await wfs.place_task(session, target, stage_type=item.stage_type)
        sequence_id, code = await next_task_code(session, target.id)
        props = dict(item.properties) if isinstance(item.properties, dict) else {}
        props['former_codes'] = [*props.get('former_codes', []), before_code]
        item.properties = props
        item.project_id, item.tenant_id = target.id, target.tenant_id
        item.workflow_id, item.stage_id, item.stage_type = (
            placement.workflow_id,
            placement.stage_id,
            placement.stage_type,
        )
        item.sequence_id, item.code = sequence_id, code
        item.task_list_id = item.iteration_id = None
        if item.id == task.id:
            item.parent_id = None
        await session.flush()
        moved.append(item)
        await events.emit(
            session,
            scope,
            'ppm.task.moved',
            'task',
            item.id,
            project_id=target.id,
            data={
                'from_project_id': source.id,
                'to_project_id': target.id,
                'old_code': before_code,
                'new_code': code,
                'name': item.name,
            },
        )
    str_ids = [str(i) for i in ids]
    await session.execute(
        update(ews_models.Timelog)
        .where(ews_models.Timelog.task_id.in_(ids))
        .values(project_id=target.id)
    )
    await session.execute(
        update(ews_models.ProjectComment)
        .where(
            ews_models.ProjectComment.object_type == 'task',
            ews_models.ProjectComment.object_id.in_(str_ids),
        )
        .values(project_id=str(target.id))
    )
    from db.models.ppm import PpmAttachment

    await session.execute(
        update(PpmAttachment)
        .where(PpmAttachment.task_id.in_(ids))
        .values(project_id=target.id)
    )
    await refresh_rollups(session, old_parent)
    await touch_project(session, source.id)
    await touch_project(session, target.id)
    return moved
