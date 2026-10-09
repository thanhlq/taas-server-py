"""My Work (taas-specs/ppm/my-work/my-work-spec.md, ADR-18, ADR-29): everything waiting for the signed-in user in
every project they can read — items they own or collaborate on, checklist steps assigned to them, unread mentions —
bucketed by *their* planned date (else the due date) in their time zone. Plans, order and snoozes are private
(``taas_ppm_my_work_plans``, never an event — Ppm-0914). Quick add without a project lands in the user's **Inbox**
(a personal project, ``kind = personal``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db.models.ews as ews_models
from db.models.ews.ews_enums import ProjectStatus
from db.models.notifications import Notification
from db.models.ppm import PpmMyWorkPlan, PpmUserSettings
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import String, and_, cast, delete, func, or_, select

from ews.security import RequestScope

from . import _access as access
from . import _events as events
from . import _work_items as items
from . import _workflow_service as wfs
from . import workflow_catalog as catalog

BUCKETS = ('overdue', 'today', 'tomorrow', 'this_week', 'later', 'no_date')
SOURCES = ('task', 'checklist_item', 'mention', 'approval')
MAX_ENTRIES = 500
DEFAULT_SETTINGS: dict[str, Any] = {
    'week_start': 1,  # ISO weekday: 1 = Monday … 7 = Sunday
    'working_days': [1, 2, 3, 4, 5],
    'day_capacity_minutes': 480,
    'default_view': 'list',
}
PRIORITY_TOKEN = re.compile(r'(?:^|\s)!([0-5])(?=\s|$)')

Task = ews_models.Task
Project = ews_models.Project


def me(scope: RequestScope) -> list[str]:
    """The refs the session user is known by on items (ADR-12): user id and e-mail, lower-case."""
    return [r for r in {str(scope.user_id).lower(), (scope.email or '').lower()} if r]


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or 'UTC')
    except ZoneInfoNotFoundError, ValueError:
        raise ClientException(detail=f'unknown time zone {tz!r}') from None


@dataclass(slots=True)
class Clock:
    today: date
    week_end: date

    @classmethod
    def of(
        cls, tz: str | None, week_start: int = 1, now: datetime | None = None
    ) -> Clock:
        today = (now or datetime.now(UTC)).astimezone(zone(tz)).date()
        # last day of the week that contains today
        start_offset = (today.isoweekday() - week_start) % 7
        return cls(today, today - timedelta(days=start_offset) + timedelta(days=6))

    def bucket(self, day: date | None) -> str:
        if day is None:
            return 'no_date'
        if day < self.today:
            return 'overdue'
        if day == self.today:
            return 'today'
        if day == self.today + timedelta(days=1):
            return 'tomorrow'
        if day <= self.week_end:
            return 'this_week'
        return 'later'


@dataclass(slots=True)
class Entry:
    source_type: str
    source_id: str
    task: Task
    project: Project
    name: str
    due: date | None
    planned: date | None = None
    sort_key: float | None = None
    snoozed_until: datetime | None = None
    role: str | None = None
    stage: ews_models.WorkflowStage | None = None
    checklist_item_id: str | None = None
    notification_id: str | None = None
    excerpt: str | None = None
    bucket: str = 'no_date'
    overdue_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _date(value: datetime | None) -> date | None:
    """Calendar dates are midnight UTC on the wire: take the date part (my-work §5.1)."""
    return value.date() if value is not None else None


async def user_settings(
    session: DBAsyncScopedSession, scope: RequestScope
) -> dict[str, Any]:
    row = await session.scalar(
        select(PpmUserSettings).where(PpmUserSettings.user_id == scope.user_id)
    )
    return {**DEFAULT_SETTINGS, **((row.settings if row else None) or {})}


async def save_settings(
    session: DBAsyncScopedSession, scope: RequestScope, patch: dict[str, Any]
) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key == 'week_start' and value in range(1, 8):
            clean[key] = int(value)
        elif (
            key == 'working_days'
            and isinstance(value, list)
            and all(d in range(1, 8) for d in value)
        ):
            clean[key] = sorted({int(d) for d in value})
        elif (
            key == 'day_capacity_minutes'
            and isinstance(value, int)
            and 0 <= value <= 24 * 60
        ):
            clean[key] = value
        elif key == 'default_view' and value in ('list', 'board', 'calendar'):
            clean[key] = value
        else:
            raise ClientException(detail=f'invalid My Work setting {key!r}')
    row = await session.scalar(
        select(PpmUserSettings).where(PpmUserSettings.user_id == scope.user_id)
    )
    if row is None:
        row = PpmUserSettings(
            tenant_id=scope.tenant_id, user_id=scope.user_id, settings={}
        )
        session.add(row)
    row.settings = {**(row.settings or {}), **clean}
    await session.flush()
    return {**DEFAULT_SETTINGS, **row.settings}


# --- Inbox (personal project, ADR-29) -------------------------------------------------------------


async def inbox(
    session: DBAsyncScopedSession, scope: RequestScope, *, create: bool
) -> Project | None:
    """The caller's personal project in the organization (created on first need)."""
    project = await session.scalar(
        select(Project).where(
            Project.tenant_id == scope.tenant_id,
            Project.organization_id == scope.organization_id,
            Project.kind == 'personal',
            Project.user_id == str(scope.user_id),
            Project.deleted_at.is_(None),
        )
    )
    if project is not None or not create:
        return project
    project = Project(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        name='Inbox',
        code='IN',
        kind='personal',
        user_id=str(scope.user_id),
        status=ProjectStatus.ACTIVE,
        last_activity_at=items.now(),
    )
    seed = wfs.seed_process(None, None)
    seed.process.save(project)
    session.add(project)
    await session.flush()
    await wfs.create_workflow(
        session,
        project,
        name=seed.workflow_name,
        stages=seed.stages,
        workflow_type=seed.workflow_type,
        is_default=True,
        template_id=None,
    )
    await access.grant_creator(scope, project.id)
    await events.emit(
        session,
        scope,
        'ppm.project.created',
        'project',
        project.id,
        project_id=project.id,
        data={'name': project.name, 'kind': 'personal'},
        cause='quick_add',
    )
    return project


# --- entries --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Filters:
    project_ids: list[UUID] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    priorities: list[int] = field(default_factory=list)
    role: str | None = None
    inbox: bool = False
    snoozed: bool = False
    q: str | None = None


async def _readable(scope: RequestScope, inbox_id: UUID | None):  # noqa: ANN202
    readable = await access.readable_projects(scope)
    personal_ok = or_(Project.kind != 'personal', Project.user_id == str(scope.user_id))
    cond = and_(readable, Project.kind != 'template', personal_ok)
    return or_(cond, Project.id == inbox_id) if inbox_id else cond


def _open_task() -> Any:
    return and_(
        Task.deleted_at.is_(None),
        Task.completed_at.is_(None),
        or_(
            Task.stage_type.is_(None),
            Task.stage_type.not_in(
                list(catalog.done_stage_types() | catalog.excluded_stage_types())
            ),
        ),
    )


async def collect(
    session: DBAsyncScopedSession, scope: RequestScope, clock: Clock, filters: Filters
) -> list[Entry]:
    """Every open entry of the caller (snoozed ones only with ``filters.snoozed``), bucketed (§5.1)."""
    refs = me(scope)
    box = await inbox(session, scope, create=False)
    readable = await _readable(scope, box.id if box else None)
    entries: list[Entry] = []
    project_filter = (
        Project.id.in_(filters.project_ids) if filters.project_ids else None
    )
    if filters.inbox:
        project_filter = Project.id == (box.id if box else None)
    want = set(filters.sources or SOURCES)

    if 'task' in want:
        tu = ews_models.TaskUser
        collab_ids = select(tu.task_id).where(
            func.lower(tu.user_id).in_(refs),
            tu.deleted_at.is_(None),
            tu.role == 'collaborator',
        )
        owner = func.lower(Task.user_id).in_(refs)
        role_cond = (
            owner
            if filters.role == 'owner'
            else Task.id.in_(collab_ids)
            if filters.role == 'collaborator'
            else or_(owner, Task.id.in_(collab_ids))
        )
        query = (
            select(Task, Project)
            .join(Project, Project.id == Task.project_id)
            .where(_open_task(), role_cond, Project.deleted_at.is_(None), readable)
        )
        if project_filter is not None:
            query = query.where(project_filter)
        if filters.priorities:
            query = query.where(Task.priority.in_(filters.priorities))
        if filters.q:
            like = f'%{filters.q.strip().lower()}%'
            query = query.where(
                or_(func.lower(Task.name).like(like), func.lower(Task.code).like(like))
            )
        for task, project in (await session.execute(query.limit(2000))).all():
            entries.append(
                Entry(
                    'task',
                    str(task.id),
                    task,
                    project,
                    task.name or '',
                    _date(task.due_date),
                    role='owner'
                    if (task.user_id or '').lower() in refs
                    else 'collaborator',
                )
            )

    if 'checklist_item' in want and not filters.role:
        item = ews_models.TaskChecklistItem
        query = (
            select(item, Task, Project)
            .join(Task, Task.id == item.task_id)
            .join(Project, Project.id == Task.project_id)
            .where(
                func.lower(item.assignee_user_id).in_(refs),
                or_(item.is_completed.is_(None), item.is_completed.is_(False)),
                _open_task(),
                Project.deleted_at.is_(None),
                readable,
            )
        )
        if project_filter is not None:
            query = query.where(project_filter)
        if filters.q:
            query = query.where(
                func.lower(item.name).like(f'%{filters.q.strip().lower()}%')
            )
        for ci, task, project in (await session.execute(query.limit(1000))).all():
            entries.append(
                Entry(
                    'checklist_item',
                    str(ci.id),
                    task,
                    project,
                    ci.name or '',
                    _date(ci.due_date) or _date(task.due_date),
                    checklist_item_id=str(ci.id),
                )
            )

    if 'mention' in want and not filters.role and not filters.inbox:
        n = Notification
        who = [n.recipient_user_id == scope.user_id]
        if scope.email:
            who.append(func.lower(n.recipient_email) == scope.email.lower())
        query = (
            select(n, Task, Project)
            .join(Task, cast(Task.id, String) == n.subject_id)
            .join(Project, Project.id == Task.project_id)
            .where(
                n.tenant_id == scope.tenant_id,
                or_(*who),
                n.kind == 'ppm:task_mentioned',
                n.read_at.is_(None),
                Task.deleted_at.is_(None),
                readable,
            )
        )
        if project_filter is not None:
            query = query.where(project_filter)
        for note, task, project in (await session.execute(query.limit(200))).all():
            entries.append(
                Entry(
                    'mention',
                    str(note.id),
                    task,
                    project,
                    task.name or '',
                    clock.today,
                    notification_id=str(note.id),
                    excerpt=(note.data or {}).get('excerpt'),
                    extra={'actor_name': note.actor_name or note.actor_ref},
                )
            )

    if 'approval' in want and not filters.role and not filters.inbox:
        from . import _approvals as approvals  # approvals → work items: imported late

        for approval, step in await approvals.waiting_for(session, scope):
            if approval.subject_type != 'task':
                continue  # timesheets / expenses / requests join with their modules
            task = await session.get(Task, UUID(approval.subject_id))
            project = (
                await session.get(Project, task.project_id)
                if task and task.project_id
                else None
            )
            if task is None or project is None or task.deleted_at is not None:
                continue
            if (
                project_filter is not None
                and filters.project_ids
                and project.id not in filters.project_ids
            ):
                continue
            if (
                filters.q
                and filters.q.strip().lower() not in (approval.title or '').lower()
            ):
                continue
            entries.append(
                Entry(
                    'approval',
                    str(approval.id),
                    task,
                    project,
                    approval.title,
                    approval.due_at.date() if approval.due_at else None,
                    extra={
                        'actor_name': approval.requested_by,
                        'step': step.step_name or step.step,
                    },
                )
            )

    # plans + snoozes (one query), stages (one query)
    if entries:
        plans = {
            (p.source_type, p.source_id): p
            for p in (
                await session.scalars(
                    select(PpmMyWorkPlan).where(
                        PpmMyWorkPlan.user_id == scope.user_id,
                        PpmMyWorkPlan.source_id.in_([e.source_id for e in entries]),
                    )
                )
            ).all()
        }
        stage_ids = {e.task.stage_id for e in entries if e.task.stage_id}
        stages = (
            {
                s.id: s
                for s in (
                    await session.scalars(
                        select(ews_models.WorkflowStage).where(
                            ews_models.WorkflowStage.id.in_(stage_ids)
                        )
                    )
                ).all()
            }
            if stage_ids
            else {}
        )
        now = datetime.now(UTC)
        kept: list[Entry] = []
        for e in entries:
            plan = plans.get((e.source_type, e.source_id))
            if plan is not None:
                e.planned, e.sort_key, e.snoozed_until = (
                    plan.planned_date,
                    plan.sort_key,
                    plan.snoozed_until,
                )
            snoozed = e.snoozed_until is not None and e.snoozed_until > now
            if snoozed != filters.snoozed:
                continue
            e.stage = stages.get(e.task.stage_id) if e.task.stage_id else None
            day = e.planned or e.due
            e.bucket = clock.bucket(day)
            if e.bucket == 'overdue':
                e.overdue_reason = (
                    'due' if e.due is not None and e.due < clock.today else 'plan'
                )
            kept.append(e)
        entries = kept
    entries.sort(
        key=lambda e: (
            BUCKETS.index(e.bucket),
            e.sort_key if e.sort_key is not None else float('inf'),
            -(e.task.priority or 0),
            e.due or date.max,
            (e.project.name or '').lower(),
            e.task.code or '',
        )
    )
    return entries


async def done_today(
    session: DBAsyncScopedSession, scope: RequestScope, clock: Clock, tz: str | None
) -> list[tuple[Task, Project]]:
    start = (
        datetime.combine(clock.today, datetime.min.time(), tzinfo=zone(tz))
        .astimezone(UTC)
        .replace(tzinfo=None)
    )
    rows = await session.execute(
        select(Task, Project)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.deleted_at.is_(None),
            Task.completed_at >= start,
            func.lower(Task.completed_by).in_(me(scope)),
            Project.deleted_at.is_(None),
        )
        .order_by(Task.completed_at.desc())
        .limit(50)
    )
    return list(rows.all())


# --- plans ----------------------------------------------------------------------------------------


async def _check_source(
    session: DBAsyncScopedSession, scope: RequestScope, source_type: str, source_id: str
) -> None:
    """The source must be one of the caller's readable entries (404 otherwise, Ppm-0914)."""
    if source_type == 'task':
        await access.load_task(session, scope, source_id)
    elif source_type == 'checklist_item':
        item = await session.get(
            ews_models.TaskChecklistItem, access.parse_uuid(source_id, 'checklist item')
        )
        if item is None:
            raise NotFoundException(detail='checklist item not found')
        await access.load_task(session, scope, item.task_id)
    elif source_type == 'approval':
        from . import _approvals as approvals

        await approvals.get(session, scope, source_id)
    elif source_type == 'mention':
        note = await session.get(
            Notification, access.parse_uuid(source_id, 'notification')
        )
        mine = note is not None and (
            note.recipient_user_id == scope.user_id
            or (
                scope.email
                and (note.recipient_email or '').lower() == scope.email.lower()
            )
        )
        if not mine:
            raise NotFoundException(detail='notification not found')
    else:
        raise ClientException(detail=f'source_type must be one of {", ".join(SOURCES)}')


async def set_plan(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    source_type: str,
    source_id: str,
    *,
    planned_date: date | None,
    sort_key: float | None,
    snoozed_until: datetime | None,
) -> PpmMyWorkPlan:
    await _check_source(session, scope, source_type, source_id)
    plan = await session.scalar(
        select(PpmMyWorkPlan).where(
            PpmMyWorkPlan.user_id == scope.user_id,
            PpmMyWorkPlan.source_type == source_type,
            PpmMyWorkPlan.source_id == source_id,
        )
    )
    if plan is None:
        plan = PpmMyWorkPlan(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            source_type=source_type,
            source_id=source_id,
        )
        session.add(plan)
    plan.planned_date, plan.sort_key, plan.snoozed_until = (
        planned_date,
        sort_key,
        snoozed_until,
    )
    await session.flush()
    return plan


async def clear_plan(
    session: DBAsyncScopedSession, scope: RequestScope, source_type: str, source_id: str
) -> None:
    await session.execute(
        delete(PpmMyWorkPlan).where(
            PpmMyWorkPlan.user_id == scope.user_id,
            PpmMyWorkPlan.source_type == source_type,
            PpmMyWorkPlan.source_id == source_id,
        )
    )


async def reschedule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    clock: Clock,
    *,
    planned_date: date,
    refs: list[tuple[str, str]] | None,
) -> int:
    """Plan every overdue entry (or ``refs``) on ``planned_date`` (Ppm-0912, Ppm-0933)."""
    if refs is None:
        entries = await collect(session, scope, clock, Filters())
        refs = [(e.source_type, e.source_id) for e in entries if e.bucket == 'overdue']
    for source_type, source_id in refs:
        await set_plan(
            session,
            scope,
            source_type,
            source_id,
            planned_date=planned_date,
            sort_key=None,
            snoozed_until=None,
        )
    return len(refs)


# --- quick add ------------------------------------------------------------------------------------


def parse_tokens(name: str) -> tuple[str, int | None]:
    """``!0``–``!5`` → priority (Ppm-0922); returns the name without the token."""
    found = PRIORITY_TOKEN.search(name)
    if not found:
        return name.strip(), None
    return (name[: found.start()] + name[found.end() :]).strip(), int(found.group(1))


async def quick_add(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    name: str,
    project_id: str | None,
    planned_date: date | None,
    due_date: datetime | None,
    priority: int | None,
) -> Task:
    clean, token_priority = parse_tokens(name)
    if project_id:
        project = await access.load_project(
            session, scope, project_id, access.TASK, 'create'
        )
    else:
        project = await inbox(session, scope, create=True)
        assert project is not None
    with events.caused_by('quick_add'):
        task = await items.create_item(
            session,
            scope,
            project,
            items.NewItem(
                name=clean,
                owner=access.author(scope),
                due_date=due_date,
                priority=priority if priority is not None else token_priority,
            ),
        )
    if planned_date is not None:
        await set_plan(
            session,
            scope,
            'task',
            str(task.id),
            planned_date=planned_date,
            sort_key=None,
            snoozed_until=None,
        )
    return task


# --- plans of closed sources (consumed events, my-work §8) ----------------------------------------


@events.subscribe
async def drop_closed_plans(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    if (
        event.topic in ('ppm.task.completed', 'ppm.task.deleted')
        and event.subject_type == 'task'
    ):
        ids = [event.subject_id, *((event.data or {}).get('subtree') or [])]
        await session.execute(
            delete(PpmMyWorkPlan).where(
                PpmMyWorkPlan.source_type == 'task', PpmMyWorkPlan.source_id.in_(ids)
            )
        )
    elif event.topic == 'ppm.checklist_item.deleted':
        item_id = (event.data or {}).get('checklist_item_id')
        if item_id:
            await session.execute(
                delete(PpmMyWorkPlan).where(
                    PpmMyWorkPlan.source_type == 'checklist_item',
                    PpmMyWorkPlan.source_id == item_id,
                )
            )
