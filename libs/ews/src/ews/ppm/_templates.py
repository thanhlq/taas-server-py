"""Project templates and duplication (taas-specs/ppm/work-model/work-model-spec.md Ppm-0880…0884, §5.5, ADR-30).

A template is a project with ``kind = template``. One copy engine serves *Save as template*, *Create from template*
and *Duplicate*: process, workflows + stages, task lists, project fields + bindings, items with their hierarchy,
checklists (unchecked), descriptions, labels, priorities, estimates and dates; optionally field values and members.
Never comments, time, approvals, activity or completion (items land in their workflow's default stage).

Assignees become **template roles** when saving as a template (one role per person, unless "Keep people"); creating
from a template maps each role to a member or leaves it unassigned. Dates move by working days (Monday–Friday until
the organization calendar exists): ``offset = working_days_between(R, d)``, new date = ``add_working_days(S, offset)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import (
    PpmCustomField,
    PpmCustomFieldBinding,
    PpmCustomFieldValue,
    PpmPhase,
    PpmWorkItemLink,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, PermissionDeniedException
from sqlalchemy import inspect, select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed

from . import _checklists as checklists
from . import _events as events
from . import _schedule as schedule
from . import _work_items as items
from . import _workflow_service as wfs
from ._access import PROJECTS, grant_creator, require_create_project

TEMPLATE = EwsResources.PROJECT_TEMPLATE.value
MAX_SYNC_ITEMS = 5000
_SKIP = {'id', 'created_at', 'updated_at', 'deleted_at', 'sa_orm_sentinel'}


# --- working days (pure) ---------------------------------------------------------------------------------


def is_working_day(day: date) -> bool:
    return day.weekday() < 5


def working_days_between(start: date, end: date) -> int:
    """Signed number of working days from ``start`` to ``end`` (0 when equal; weekends do not count)."""
    if end == start:
        return 0
    sign = 1 if end > start else -1
    a, b = (start, end) if sign > 0 else (end, start)
    days = (b - a).days
    full, rest = divmod(days, 7)
    count = full * 5
    d = a
    for _ in range(rest):
        d += timedelta(days=1)
        if is_working_day(d):
            count += 1
    return sign * count


def add_working_days(start: date, offset: int) -> date:
    """``start`` moved by ``offset`` working days; a non-working ``start`` first moves to the next working day."""
    d = start
    while not is_working_day(d):
        d += timedelta(days=1)
    step = 1 if offset >= 0 else -1
    left = abs(offset)
    while left:
        d += timedelta(days=step)
        if is_working_day(d):
            left -= 1
    return d


def shift[D: (datetime, date)](
    value: D | None, reference: date | None, start: date | None
) -> D | None:
    """``value`` moved by working days from ``reference`` to ``start`` (a datetime keeps its time)."""
    if value is None or reference is None or start is None:
        return value
    day = value.date() if isinstance(value, datetime) else value
    moved = add_working_days(start, working_days_between(reference, day))
    return (
        datetime.combine(moved, value.time()) if isinstance(value, datetime) else moved
    )


def reference_date(
    project: ews_models.Project, tasks: list[ews_models.Task]
) -> date | None:
    """The template's reference date ``R``: its start date, else its earliest item date."""
    if project.start_date:
        return project.start_date.date()
    days = [
        d.date() for t in tasks for d in (t.start_date, t.due_date) if d is not None
    ]
    return min(days) if days else None


# --- permissions ------------------------------------------------------------------------------------------


async def require_save_template(scope: RequestScope, project_id: UUID) -> None:
    if not await PROJECTS.allowed(scope, project_id, TEMPLATE, 'create'):
        raise PermissionDeniedException(detail=f'missing permission {TEMPLATE}:create')


async def require_read_templates(scope: RequestScope) -> None:
    if not await is_allowed(scope, TEMPLATE, 'read', scope.org_domains()):
        raise PermissionDeniedException(detail=f'missing permission {TEMPLATE}:read')


# --- copy -------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class CopyOptions:
    kind: str = 'project'
    name: str = ''
    code: str | None = None
    start_date: date | None = None
    role_map: dict[str, str | None] = field(default_factory=dict)
    keep_people: bool = False
    roles_from_people: bool = False
    """Save as template: owners / collaborators become template roles."""
    include_field_values: bool = False
    include_members: bool = False
    category: str | None = None
    cause: str = 'template'


def _copy_columns(row: Any, **override: Any) -> dict[str, Any]:
    values = {
        c.key: getattr(row, c.key)
        for c in inspect(type(row)).column_attrs
        if c.key not in _SKIP
    }
    values.update(override)
    return values


def _role_name(person: str) -> str:
    local = person.split('@', 1)[0].replace('.', ' ').replace('_', ' ').strip()
    return (local.title() or 'Role')[:80]


async def _live_tasks(
    session: DBAsyncScopedSession, project_id: UUID
) -> list[ews_models.Task]:
    t = ews_models.Task
    rows = list(
        (
            await session.scalars(
                select(t)
                .where(t.project_id == project_id, t.deleted_at.is_(None))
                .order_by(t.sequence_id, t.id)
            )
        ).all()
    )
    by_id = {r.id: r for r in rows}

    def depth(task: ews_models.Task) -> int:
        d, cur = 0, task
        while cur.parent_id and cur.parent_id in by_id and d < 5:
            d, cur = d + 1, by_id[cur.parent_id]
        return d

    return sorted(rows, key=lambda r: (depth(r), r.sequence_id or 0))


async def copy_project(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    source: ews_models.Project,
    options: CopyOptions,
) -> ews_models.Project:
    """The one transactional copy command (Ppm-0881, Ppm-0882, Ppm-0884)."""
    if source.organization_id != scope.organization_id:
        raise ClientException(
            detail='the source project belongs to another organization'
        )
    tasks = await _live_tasks(session, source.id)
    if len(tasks) > MAX_SYNC_ITEMS:
        raise ClientException(
            detail=f'more than {MAX_SYNC_ITEMS} items', extra={'code': 'too_large'}
        )
    name = (options.name or source.name or '').strip()
    if not name:
        raise ClientException(detail='a project needs a name')
    reference = reference_date(source, tasks)
    start = options.start_date if options.kind != 'template' else None
    move = (lambda d: shift(d, reference, start)) if start else (lambda d: d)  # noqa: E731

    template_settings = (
        dict((source.settings or {}).get('template') or {})
        if isinstance(source.settings, dict)
        else {}
    )
    roles: dict[str, str] = {
        r['key']: r['name']
        for r in template_settings.get('roles') or []
        if isinstance(r, dict)
    }
    person_role: dict[str, str] = {}
    if options.roles_from_people:
        people = []
        collabs = await items.collaborators(session, [t.id for t in tasks])
        for t in tasks:
            people += [p for p in [t.user_id, *collabs.get(t.id, [])] if p]
        for person in dict.fromkeys(p.lower() for p in people):
            key = f'role_{len(person_role) + 1}'
            person_role[person] = key
            roles[key] = _role_name(person)

    settings = (
        {k: v for k, v in (source.settings or {}).items() if k != 'template'}
        if isinstance(source.settings, dict)
        else {}
    )
    if options.kind == 'template':
        settings['template'] = {
            'roles': [{'key': k, 'name': n} for k, n in roles.items()],
            'reference_date': reference.isoformat() if reference else None,
            'category': options.category or template_settings.get('category'),
            'source_project_id': str(source.id),
        }
    project = ews_models.Project(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        name=name[:200],
        code=(options.code or source.code),
        description=source.description,
        html_text=source.html_text,
        content_type=source.content_type,
        status='New',
        kind=options.kind,
        color=source.color,
        icon_name=source.icon_name,
        default_view=source.default_view,
        tags=dict(source.tags or {}) if isinstance(source.tags, dict) else source.tags,
        workflow=dict(source.workflow or {})
        if isinstance(source.workflow, dict)
        else source.workflow,
        settings=settings,
        start_date=move(source.start_date)
        if options.kind != 'template'
        else source.start_date,
        due_date=move(source.due_date)
        if options.kind != 'template'
        else source.due_date,
        client_id=source.client_id,
        user_id=(scope.email or str(scope.user_id)),
        created_from_template_id=source.id
        if source.kind == 'template' and options.kind != 'template'
        else None,
        last_activity_at=items.now(),
    )
    session.add(project)
    await session.flush()
    await grant_creator(scope, project.id)

    # workflows + stages
    stage_map: dict[UUID, UUID] = {}
    workflow_map: dict[UUID, UUID] = {}
    for workflow in await wfs.load_workflows(session, source.id):
        new_wf = ews_models.Workflow(**_copy_columns(workflow, project_id=project.id))
        session.add(new_wf)
        await session.flush()
        workflow_map[workflow.id] = new_wf.id
        for stage in (await wfs.load_stages(session, [workflow.id])).get(
            workflow.id
        ) or []:
            new_stage = ews_models.WorkflowStage(
                **_copy_columns(stage, workflow_id=new_wf.id, project_id=project.id)
            )
            session.add(new_stage)
            await session.flush()
            stage_map[stage.id] = new_stage.id

    # task lists
    list_map: dict[UUID, UUID] = {}
    tl = ews_models.TaskList
    for row in (
        await session.scalars(
            select(tl).where(tl.project_id == source.id, tl.deleted_at.is_(None))
        )
    ).all():
        new_list = tl(**_copy_columns(row, project_id=project.id))
        session.add(new_list)
        await session.flush()
        list_map[row.id] = new_list.id

    # project fields + bindings
    field_map: dict[UUID, UUID] = {}
    f = PpmCustomField
    for row in (
        await session.scalars(
            select(f).where(f.project_id == source.id, f.archived_at.is_(None))
        )
    ).all():
        new_field = f(
            **_copy_columns(row, project_id=project.id, tenant_id=scope.tenant_id)
        )
        session.add(new_field)
        await session.flush()
        field_map[row.id] = new_field.id
    b = PpmCustomFieldBinding
    for row in (
        await session.scalars(select(b).where(b.project_id == source.id))
    ).all():
        session.add(
            b(
                **_copy_columns(
                    row,
                    project_id=project.id,
                    field_id=field_map.get(row.field_id, row.field_id),
                )
            )
        )
    await session.flush()

    # phases (planned windows shift with the dates)
    phase_map: dict[UUID, UUID] = {}
    for row in await schedule.phases_of(session, source.id):
        new_phase = PpmPhase(
            **_copy_columns(
                row,
                project_id=project.id,
                tenant_id=scope.tenant_id,
                planned_start=move(row.planned_start),
                planned_finish=move(row.planned_finish),
            )
        )
        session.add(new_phase)
        await session.flush()
        phase_map[row.id] = new_phase.id

    # items (parents first)
    task_map: dict[UUID, UUID] = {}
    collabs = await items.collaborators(session, [t.id for t in tasks])

    from_template = source.kind == 'template' and options.kind == 'project'

    def people_of(t: ews_models.Task) -> tuple[str | None, list[str]]:
        """Owner + collaborators of the copy: kept, mapped from the template roles, or none (roles only)."""
        if options.keep_people:
            return t.user_id, collabs.get(t.id, [])
        if from_template:
            roles = (
                (t.properties or {}).get('template_roles') or {}
                if isinstance(t.properties, dict)
                else {}
            )
            owner = options.role_map.get(roles.get('owner') or '') or None
            mapped = [
                options.role_map.get(r or '') for r in roles.get('collaborators') or []
            ]
            return owner, [m for m in mapped if m and m != owner]
        return None, []

    with schedule.batch():  # one recalculation after the copy
        for t in tasks:
            props = t.properties if isinstance(t.properties, dict) else {}
            template_roles = props.get('template_roles') or {}
            owner, collaborators_out = people_of(t)
            workflow_id = workflow_map.get(t.workflow_id) if t.workflow_id else None
            with events.caused_by(options.cause):
                new = await items.create_item(
                    session,
                    scope,
                    project,
                    items.NewItem(
                        name=t.name or '',
                        description=t.description,
                        description_html=t.html_text,
                        description_doc=t.description_doc,
                        workflow_id=str(workflow_id) if workflow_id else None,
                        work_item_type=t.work_item_type,
                        parent_id=task_map.get(t.parent_id) if t.parent_id else None,
                        requested_user_id=t.requested_user_id
                        if options.keep_people
                        else None,
                        owner=owner,
                        collaborators=collaborators_out,
                        task_list_id=list_map.get(t.task_list_id)
                        if t.task_list_id
                        else None,
                        labels=list((t.tags or {}).get('labels') or [])
                        if isinstance(t.tags, dict)
                        else None,
                        priority=t.priority,
                        start_date=move(t.start_date),
                        due_date=move(t.due_date),
                        estimated_minutes=t.estimated_minutes,
                        progress_mode=t.progress_mode,
                        recurrence_rule=t.recurrence_rule,
                        created_from_template_item_id=t.id,
                        schedule={
                            k: v
                            for k, v in {
                                'phase_id': phase_map.get(t.phase_id)
                                if t.phase_id and not t.parent_id
                                else None,
                                'duration_days': t.duration_days,
                                'schedule_mode': t.schedule_mode,
                                'constraint_type': t.constraint_type,
                                'constraint_date': move(t.constraint_date),
                            }.items()
                            if v is not None
                        },
                        cause=options.cause,
                    ),
                )
            if options.roles_from_people:
                roles_of = {
                    'owner': person_role.get((t.user_id or '').lower()),
                    'collaborators': [
                        person_role.get(c.lower()) for c in collabs.get(t.id, [])
                    ],
                }
                new.properties = {**(new.properties or {}), 'template_roles': roles_of}
            elif template_roles and options.kind == 'template':
                new.properties = {
                    **(new.properties or {}),
                    'template_roles': template_roles,
                }
            task_map[t.id] = new.id
            for step in await checklists.listing(session, t.id):
                await checklists.add(
                    session,
                    scope,
                    new,
                    name=step.name or '',
                    assignee=step.assignee_user_id if options.keep_people else None,
                    due_date=move(step.due_date),
                    mandatory=bool(step.is_mandatory),
                )
            if options.include_field_values:
                v = PpmCustomFieldValue
                for value in (
                    await session.scalars(select(v).where(v.task_id == t.id))
                ).all():
                    session.add(
                        v(
                            **_copy_columns(
                                value,
                                task_id=new.id,
                                field_id=field_map.get(value.field_id, value.field_id),
                            )
                        )
                    )
        await session.flush()

    # links between copied items (type, lag)
    for link in await schedule.project_links(session, source.id):
        if link.source_task_id in task_map and link.target_task_id in task_map:
            session.add(
                PpmWorkItemLink(
                    **_copy_columns(
                        link,
                        tenant_id=scope.tenant_id,
                        organization_id=project.organization_id,
                        source_task_id=task_map[link.source_task_id],
                        target_task_id=task_map[link.target_task_id],
                        source_project_id=project.id,
                        target_project_id=project.id,
                        created_by=scope.email or str(scope.user_id),
                    )
                )
            )
    await session.flush()
    if options.kind != 'template' and await schedule.has_auto_items(session, project):
        await schedule.recalculate(session, scope, project, cause=options.cause)

    if options.include_members:
        from ._members import members, set_member

        for m in await members(session, scope, source):
            if not m.inherited and m.user_id != str(scope.user_id):
                await set_member(session, scope, project, m.user_id, m.role)

    await events.emit(
        session,
        scope,
        'ppm.project_template.created'
        if options.kind == 'template'
        else 'ppm.project.created',
        'project',
        project.id,
        project_id=project.id,
        data={
            'name': project.name,
            'code': project.code,
            'kind': project.kind,
            'source_project_id': str(source.id),
            'template_id': str(source.id) if source.kind == 'template' else None,
            'items': len(task_map),
        },
        cause=options.cause,
    )
    return project


# --- gallery -----------------------------------------------------------------------------------------------


def template_summary(
    project: ews_models.Project,
    item_count: int,
    milestones: int,
    working_days: int | None,
) -> dict[str, Any]:
    t = (
        (project.settings or {}).get('template') or {}
        if isinstance(project.settings, dict)
        else {}
    )
    return {
        'id': str(project.id),
        'name': project.name,
        'code': project.code,
        'description': project.description,
        'color': project.color,
        'category': t.get('category'),
        'roles': t.get('roles') or [],
        'items': item_count,
        'milestones': milestones,
        'working_days': working_days,
    }


async def gallery(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    q: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    await require_read_templates(scope)
    p, t = ews_models.Project, ews_models.Task
    query = select(p).where(
        p.organization_id == scope.organization_id,
        p.kind == 'template',
        p.deleted_at.is_(None),
    )
    if q:
        query = query.where(p.name.ilike(f'%{q.strip()}%'))
    out = []
    for project in (await session.scalars(query.order_by(p.name))).all():
        summary_category = (
            ((project.settings or {}).get('template') or {}).get('category')
            if isinstance(project.settings, dict)
            else None
        )
        if category and summary_category != category:
            continue
        rows = list(
            (
                await session.scalars(
                    select(t).where(t.project_id == project.id, t.deleted_at.is_(None))
                )
            ).all()
        )
        reference = reference_date(project, rows)
        ends = [d.date() for r in rows for d in (r.due_date,) if d is not None]
        span = (
            working_days_between(reference, max(ends)) + 1
            if reference and ends
            else None
        )
        out.append(
            template_summary(
                project,
                len(rows),
                sum(1 for r in rows if r.behaviour == 'milestone'),
                span,
            )
        )
    return out


async def save_as_template(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    source: ews_models.Project,
    *,
    name: str,
    keep_people: bool,
    include_field_values: bool,
    include_members: bool,
    category: str | None,
) -> ews_models.Project:
    await require_save_template(scope, source.id)
    return await copy_project(
        session,
        scope,
        source,
        CopyOptions(
            kind='template',
            name=name,
            keep_people=keep_people,
            roles_from_people=not keep_people,
            include_field_values=include_field_values,
            include_members=include_members,
            category=category,
        ),
    )


async def instantiate(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    template: ews_models.Project,
    *,
    name: str,
    code: str | None,
    start_date: date,
    role_map: dict[str, str | None],
    include_field_values: bool,
    include_members: bool,
) -> ews_models.Project:
    await require_read_templates(scope)
    await require_create_project(scope)
    if template.kind != 'template':
        raise ClientException(detail='not a project template')
    return await copy_project(
        session,
        scope,
        template,
        CopyOptions(
            kind='project',
            name=name,
            code=code,
            start_date=start_date,
            role_map={k: (v or None) for k, v in role_map.items()},
            include_field_values=include_field_values,
            include_members=include_members,
        ),
    )


async def duplicate(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    source: ews_models.Project,
    *,
    name: str,
    start_date: date | None,
    include_field_values: bool,
    include_members: bool,
) -> ews_models.Project:
    await require_create_project(scope)
    return await copy_project(
        session,
        scope,
        source,
        CopyOptions(
            kind='project',
            name=name,
            start_date=start_date,
            keep_people=True,
            include_field_values=include_field_values,
            include_members=include_members,
            cause='duplicate',
        ),
    )
