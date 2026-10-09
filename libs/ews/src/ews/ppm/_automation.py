"""PPM automation engine V2 (taas-specs/ppm/automation/automation-spec.md Part B, ADR-46): project rules WHEN trigger ·
IF conditions · THEN actions, run **as their owner** through the same commands as the UI.

- Event rules run in-process on ``_events`` (subscriber, like the system rules — ADR-38): candidate rules of the event's
  project, trigger filters, item-type filter, conditions on the current state, then the actions in a savepoint.
- Relative (due in / overdue by / start reached / no activity) and scheduled rules run from the job
  ``ppm.automation_tick`` (60 s): relative rules scan hourly, scheduled ones at their next instant (UTC).
- Each live run is one row (``taas_ppm_automation_runs``): ``(rule_id, occurrence_key)`` is unique, so an occurrence
  runs once; failures roll the run's writes back; 3 failures in a row pause the rule and tell its owner; 100 runs an
  hour per rule, then ``throttled``; depth ≥ 3 or a rule's own run → ``loop_blocked`` / skipped; undo restores the
  *before* values when the targets still hold the run's *after* values.
"""

from __future__ import annotations

import time as clock
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import (
    PpmAuditEvent,
    PpmAutomationRule,
    PpmAutomationRun,
    PpmHealthSnapshot,
    PpmSettings,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ews.authz import EwsResources, grants_in
from ews.notifications import Kind, notify, register_job, register_kinds
from ews.security import RequestScope, is_allowed, scope_of
from ews.shared import ConflictException

from . import _access as access
from . import _approvals as approvals
from . import _automation_rules as rules
from . import _checklists as checklists
from . import _comments as comments
from . import _events as events
from . import _item_update as item_update
from . import _schedule as schedule
from . import _settings
from . import _work_items as items
from .controllers._task_support import task_watchers

AUTOMATION = EwsResources.AUTOMATION.value
Rule = PpmAutomationRule
Run = PpmAutomationRun
Task = ews_models.Task
Project = ews_models.Project

MAX_DEPTH = 3
MAX_RUNS_PER_HOUR = 100
MAX_ACTIVE_PER_PROJECT = 25
FAILURES_TO_PAUSE = 3
RETENTION_DAYS = 90
SCAN_LIMIT = 5000
TICK_RULES = 50
RELATIVE_EVERY = timedelta(hours=1)

register_kinds(
    Kind('ppm:automation', 'ppm', email='instant'),
    Kind('ppm:automation_failed', 'ppm', email='instant', mandatory=True),
)

_depth: ContextVar[int] = ContextVar('ppm_automation_depth', default=0)
_running: ContextVar[frozenset[UUID]] = ContextVar(
    'ppm_automation_running', default=frozenset()
)


def _now() -> datetime:
    return datetime.now(UTC)


def _invalid(issues: list[rules.Issue]) -> ClientException:
    return ClientException(
        detail='the rule is not valid',
        extra={'code': 'invalid_rule', 'issues': [i.as_dict() for i in issues]},
    )


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return (
            value.date().isoformat()
            if value.time() == datetime.min.time()
            else value.isoformat()
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


# --- rules ----------------------------------------------------------------------------------------


async def load_rule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rule_id: str,
    action: str = 'read',
) -> tuple[PpmAutomationRule, ews_models.Project]:
    """A rule of the organization with ``ppm.automation:<action>`` on its project (404 otherwise)."""
    row = await session.scalar(
        select(Rule).where(
            Rule.id == access.parse_uuid(rule_id, 'rule'),
            Rule.organization_id == scope.organization_id,
            Rule.deleted_at.is_(None),
        )
    )
    if row is None or row.project_id is None:
        raise NotFoundException(detail='rule not found')
    project = await access.load_project(
        session, scope, row.project_id, AUTOMATION, action
    )
    return row, project


async def rules_of(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project_id: UUID | None,
    status: str | None,
) -> list[PpmAutomationRule]:
    q = select(Rule).where(
        Rule.organization_id == scope.organization_id, Rule.deleted_at.is_(None)
    )
    if project_id:
        await access.load_project(session, scope, project_id, AUTOMATION, 'read')
        q = q.where(Rule.project_id == project_id)
    else:
        q = q.where(
            Rule.project_id.in_(
                select(Project.id).where(await access.readable_projects(scope))
            )
        )
    if status:
        q = q.where(Rule.status == status)
    out = []
    for row in (
        await session.scalars(q.order_by(Rule.position, Rule.created_at))
    ).all():
        if project_id or await is_allowed(
            scope, AUTOMATION, 'read', access.project_domains(scope, row.project_id)
        ):
            out.append(row)
    return out


def _definition(data: dict[str, Any]) -> dict[str, Any]:
    """The rule JSON of a request, validated (400 ``invalid_rule`` with JSON paths)."""
    rule = {
        'trigger_type': data.get('trigger_type'),
        'trigger': data.get('trigger'),
        'conditions': data.get('conditions') or [],
        'actions': data.get('actions'),
        'item_types': data.get('item_types') or None,
    }
    issues = rules.validate(rule)
    if issues:
        raise _invalid(issues)
    return rule


def _next_scan(rule: PpmAutomationRule, now: datetime) -> datetime | None:
    if rule.status != 'active' or rule.trigger_type == 'event':
        return None
    if rule.trigger_type == 'relative':
        return now
    return rules.next_run(rule.trigger, now)


async def _check_quota(
    session: DBAsyncScopedSession, project_id: UUID, ignore: UUID | None = None
) -> None:
    active = await session.scalar(
        select(func.count(Rule.id)).where(
            Rule.project_id == project_id,
            Rule.status == 'active',
            Rule.deleted_at.is_(None),
            Rule.id != ignore if ignore else True,
        )
    )
    if (active or 0) >= MAX_ACTIVE_PER_PROJECT:
        raise ConflictException(
            detail=f'a project has at most {MAX_ACTIVE_PER_PROJECT} active rules',
            extra={'code': 'rule_limit'},
        )


def _snapshot(rule: PpmAutomationRule) -> dict[str, Any]:
    return {
        'name': rule.name,
        'status': rule.status,
        'trigger_type': rule.trigger_type,
        'trigger': rule.trigger,
        'conditions': rule.conditions,
        'actions': rule.actions,
        'item_types': rule.item_types,
    }


async def _emit(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    rule: PpmAutomationRule,
    topic: str,
    **kw: Any,
) -> None:
    await events.emit(
        session,
        scope,
        topic,
        'automation_rule',
        rule.id,
        project_id=rule.project_id,
        tenant_id=rule.tenant_id,
        organization_id=rule.organization_id,
        **kw,
    )


async def create_rule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    data: dict[str, Any],
) -> PpmAutomationRule:
    """A project rule owned by the caller (``ppm.automation:create``), disabled unless ``status = active``."""
    await access.require(scope, project.id, AUTOMATION, 'create')
    definition = _definition(data)
    name = str(data.get('name') or '').strip()[:200]
    if not name:
        raise _invalid([rules.Issue('name', 'a name is required')])
    status = 'active' if data.get('status') == 'active' else 'disabled'
    if status == 'active':
        await _check_quota(session, project.id)
    rule = Rule(
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        scope_type='project',
        project_id=project.id,
        name=name,
        description=(str(data.get('description') or '').strip() or None),
        status=status,
        owner=access.author(scope),
        owner_user_id=scope.user_id,
        trigger_event=rules.trigger_event(definition),
        template_key=data.get('template_key')
        if data.get('template_key') in rules.TEMPLATE_BY_KEY
        else None,
        version=1,
        **definition,
    )
    rule.next_run_at = _next_scan(rule, _now())
    session.add(rule)
    await session.flush()
    await _emit(
        session, scope, rule, 'ppm.automation_rule.created', data=_snapshot(rule)
    )
    return rule


async def update_rule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rule: PpmAutomationRule,
    data: dict[str, Any],
    version: int,
) -> PpmAutomationRule:
    """Change name / description / trigger / conditions / actions / item types on ``version`` (409 ``stale_rule``)."""
    if rule.version != version:
        raise ConflictException(
            detail='the rule changed meanwhile', extra={'code': 'stale_rule'}
        )
    before = _snapshot(rule)
    merged = {**_snapshot(rule), **{k: v for k, v in data.items() if v is not None}}
    definition = _definition(merged)
    if 'name' in data and data['name'] is not None:
        name = str(data['name']).strip()[:200]
        if not name:
            raise _invalid([rules.Issue('name', 'a name is required')])
        rule.name = name
    if 'description' in data and data['description'] is not None:
        rule.description = str(data['description']).strip() or None
    for key, value in definition.items():
        setattr(rule, key, value)
    rule.trigger_event = rules.trigger_event(definition)
    rule.version += 1
    rule.next_run_at = _next_scan(rule, _now())
    await session.flush()
    await _emit(
        session,
        scope,
        rule,
        'ppm.automation_rule.updated',
        changes=events.diff(before, _snapshot(rule)),
    )
    return rule


async def set_status(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rule: PpmAutomationRule,
    status: str,
) -> PpmAutomationRule:
    """Enable (re-validated, quota, failures reset) or disable a rule."""
    if status == rule.status:
        return rule
    if status == 'active':
        issues = rules.validate(_snapshot(rule))
        if issues:
            raise _invalid(issues)
        await _check_quota(session, rule.project_id, rule.id)
        rule.failures = 0
    rule.status = status
    rule.version += 1
    rule.next_run_at = _next_scan(rule, _now())
    await session.flush()
    await _emit(
        session,
        scope,
        rule,
        'ppm.automation_rule.enabled'
        if status == 'active'
        else 'ppm.automation_rule.disabled',
    )
    return rule


async def delete_rule(
    session: DBAsyncScopedSession, scope: RequestScope, rule: PpmAutomationRule
) -> None:
    rule.deleted_at = _now()
    rule.status = 'disabled'
    await session.flush()
    await _emit(
        session, scope, rule, 'ppm.automation_rule.deleted', data={'name': rule.name}
    )


async def runs_of(
    session: DBAsyncScopedSession,
    *,
    rule_id: UUID | None = None,
    subject_id: str | None = None,
    limit: int = 50,
) -> list[PpmAutomationRun]:
    q = select(Run).where(Run.mode == 'live')
    if rule_id:
        q = q.where(Run.rule_id == rule_id)
    if subject_id:
        q = q.where(Run.subject_type == 'task', Run.subject_id == subject_id)
    return list(
        (
            await session.scalars(
                q.order_by(Run.created_at.desc()).limit(max(1, min(limit, 200)))
            )
        ).all()
    )


# --- subject state --------------------------------------------------------------------------------


def item_state(t: ews_models.Task) -> dict[str, Any]:
    return {
        'id': str(t.id),
        'code': t.code,
        'name': t.name,
        'type': t.work_item_type,
        'behaviour': t.behaviour,
        'stage_type': t.stage_type,
        'stage_id': str(t.stage_id) if t.stage_id else None,
        'priority': t.priority,
        'assignee': t.user_id,
        'labels': items.task_labels(t),
        'due_date': _plain(t.due_date),
        'start_date': _plain(t.start_date),
        'estimate': t.estimated_minutes,
        'progress': t.progress,
    }


async def project_state(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> dict[str, Any]:
    health = await session.scalar(
        select(PpmHealthSnapshot.overall_effective)
        .where(PpmHealthSnapshot.project_id == project.id)
        .order_by(PpmHealthSnapshot.snapshot_date.desc())
        .limit(1)
    )
    return {
        'id': str(project.id),
        'name': project.name,
        'status': project.status,
        'health': health,
    }


async def _subject_task(
    session: DBAsyncScopedSession, event: events.Event
) -> ews_models.Task | None:
    ref = None
    if event.subject_type == 'task':
        ref = event.subject_id
    elif (event.data or {}).get('subject_type') == 'task':
        ref = event.data.get('subject_id')
    if not ref:
        return None
    try:
        return await session.get(Task, UUID(str(ref)))
    except ValueError:
        return None


# --- running --------------------------------------------------------------------------------------


@dataclass(slots=True)
class RunContext:
    rule: PpmAutomationRule
    project: ews_models.Project
    task: ews_models.Task | None
    occurrence: str
    event: events.Event | None = None
    trigger_date: date | None = None

    def tokens(self) -> dict[str, Any]:
        actor = self.event.actor if self.event else None
        return {
            'item.code': self.task.code if self.task else None,
            'item.name': self.task.name if self.task else None,
            'project.name': self.project.name,
            'trigger.date': (self.trigger_date or _now().date()).isoformat(),
            'actor.name': (actor.name or actor.ref) if actor else None,
        }


async def _task_for(
    session: DBAsyncScopedSession, scope: RequestScope, rc: RunContext
) -> ews_models.Task:
    if rc.task is None:
        raise ClientException(
            detail='this action needs an item', extra={'code': 'no_item'}
        )
    task, _ = await access.load_task(session, scope, rc.task.id, access.TASK, 'update')
    return task


def _fields(task: ews_models.Task, keys: tuple[str, ...]) -> dict[str, Any]:
    out = {}
    for k in keys:
        out[k] = items.task_labels(task) if k == 'labels' else _plain(getattr(task, k))
    return out


async def _update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rc: RunContext,
    patch: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    task = await _task_for(session, scope, rc)
    before = _fields(task, keys)
    await item_update.update_item(session, scope, task, rc.project, patch)
    after = _fields(task, keys)
    return {
        'target': str(task.id),
        'before': before,
        'after': after,
        'undo': {'kind': 'restore'},
    }


async def _recipients(
    session: DBAsyncScopedSession, rc: RunContext, who: list[str]
) -> list[str]:
    out: list[str] = []
    for r in who:
        if r == 'assignee' and rc.task:
            collabs = await items.collaborators(session, [rc.task.id])
            out += [u for u in [rc.task.user_id, *collabs.get(rc.task.id, [])] if u]
        elif r == 'owner' and rc.project.user_id:
            out.append(rc.project.user_id)
        elif r == 'project_admins':
            out += [
                u
                for u, role, _ in await grants_in(
                    [access.project_domain(rc.project.id)]
                )
                if role == 'project_admin'
            ]
        elif r == 'actor' and rc.event and rc.event.actor.ref:
            out.append(rc.event.actor.ref)
        elif r == 'watchers' and rc.task:
            out += task_watchers(rc.task)
        elif '@' in r:
            out.append(r)
    return list(dict.fromkeys(out))


async def _act(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rc: RunContext,
    i: int,
    a: dict[str, Any],
) -> dict[str, Any]:
    """One action as ``scope`` (the owner); returns ``{type, target, before, after, undo}``."""
    kind = a['type']
    tokens = rc.tokens()
    if kind == 'notify':
        recipients = await _recipients(session, rc, a['recipients'])
        title = rules.render(a['message'], tokens)[:300]
        link = (
            f'/ppm/projects/{rc.project.id}?task={rc.task.id}'
            if rc.task
            else f'/ppm/projects/{rc.project.id}/settings?tab=overview'
        )
        sent = await notify(
            session,
            tenant_id=rc.project.tenant_id,
            organization_id=rc.project.organization_id,
            kind='ppm:automation',
            recipients=recipients,
            title=title,
            body=rc.rule.name,
            link=link,
            subject_type='task' if rc.task else 'project',
            subject_id=str(rc.task.id if rc.task else rc.project.id),
            project_id=rc.project.id,
            actor_name=rc.rule.name,
            via='automation',
            occurrence=f'automation:{rc.rule.id}:{rc.occurrence}:{i}',
            data={'rule': rc.rule.name},
        )
        return {'after': {'recipients': len(recipients), 'notified': sent}}
    if kind == 'create_item':
        base = rc.trigger_date or _now().date()
        due = (
            rules.add_days(base, int(a['due_in_days']), bool(a.get('working_days')))
            if a.get('due_in_days') is not None
            else None
        )
        owner = a.get('assignee')
        new = items.NewItem(
            name=rules.render(a['name'], tokens)[:500],
            work_item_type=a.get('item_type') or None,
            parent_id=rc.task.id if a.get('parent') == 'trigger' and rc.task else None,
            owner=owner if isinstance(owner, str) and '@' in owner else None,
            due_date=datetime.combine(due, datetime.min.time()) if due else None,
            cause='rule',
        )
        await access.require(scope, rc.project.id, access.TASK, 'create')
        task = await items.create_item(session, scope, rc.project, new)
        if a.get('link') and rc.task:
            await schedule.create_link(
                session, scope, rc.project, rc.task, task, a['link'], 0
            )
        return {
            'target': str(task.id),
            'after': {'id': str(task.id), 'code': task.code, 'name': task.name},
            'undo': {'kind': 'delete_item', 'id': str(task.id)},
        }
    if kind == 'assign':
        to = a.get('to')
        if to == 'actor':
            to = rc.event.actor.ref if rc.event else None
        elif a.get('round_robin_role'):
            to = await _round_robin(session, scope, rc, a['round_robin_role'])
        if not to:
            raise ClientException(
                detail='nobody to assign', extra={'code': 'no_assignee'}
            )
        return await _update(session, scope, rc, {'user_id': to}, ('user_id',))
    if kind == 'set_field':
        task = await _task_for(session, scope, rc)
        f = a['field']
        if f in ('labels_add', 'labels_remove'):
            labels = items.task_labels(task)
            value = str(a['value']).strip()
            labels = (
                [*labels, value]
                if f == 'labels_add' and value not in labels
                else labels
            )
            labels = (
                [x for x in labels if x != value] if f == 'labels_remove' else labels
            )
            return await _update(session, scope, rc, {'labels': labels}, ('labels',))
        return await _update(session, scope, rc, {f: a['value']}, (f,))
    if kind == 'move_stage':
        patch = (
            {'stage_id': a['stage_id']}
            if a.get('stage_id')
            else {'stage_type': a['stage_type']}
        )
        return await _update(session, scope, rc, patch, ('stage_id',))
    if kind == 'set_due':
        task = await _task_for(session, scope, rc)
        frm = a.get('from', 'trigger')
        base = {
            'trigger': rc.trigger_date or _now().date(),
            'today': _now().date(),
            'start_date': task.start_date.date() if task.start_date else None,
            'due_date': task.due_date.date() if task.due_date else None,
        }[frm]
        if base is None:
            raise ClientException(
                detail=f'the item has no {frm}', extra={'code': 'no_date'}
            )
        due = rules.add_days(base, int(a['days']), bool(a.get('working_days')))
        return await _update(
            session,
            scope,
            rc,
            {'due_date': f'{due.isoformat()}T00:00:00'},
            ('due_date',),
        )
    if kind == 'add_checklist':
        from . import (
            _checklist_templates as checklist_templates,
        )  # templates import items: late import

        task = await _task_for(session, scope, rc)
        template = await session.scalar(
            select(ews_models.ChecklistTemplate).where(
                ews_models.ChecklistTemplate.id
                == access.parse_uuid(a['template_id'], 'template'),
            )
        )
        if template is None:
            raise ClientException(
                detail='checklist template not found', extra={'code': 'no_template'}
            )
        before = {x.id for x in await checklists.listing(session, task.id)}
        await checklist_templates.apply(session, scope, task, template)
        added = [
            str(x.id)
            for x in await checklists.listing(session, task.id)
            if x.id not in before
        ]
        return {
            'target': str(task.id),
            'after': {'added': len(added)},
            'undo': {'kind': 'delete_checklist', 'ids': added},
        }
    if kind == 'add_comment':
        task = await _task_for(session, scope, rc) if rc.task else None
        saved = await comments.create(
            session,
            scope,
            rc.project,
            task,
            text=rules.render(a['text'], tokens),
            html=None,
        )
        return {
            'target': str(task.id) if task else str(rc.project.id),
            'after': {'comment': str(getattr(saved, 'id', ''))},
        }
    if kind == 'start_approval':
        task = await _task_for(session, scope, rc)
        approval = await approvals.request(
            session,
            scope,
            subject_key='task',
            subject_id=str(task.id),
            steps=[
                approvals.StepIn(
                    rule=a.get('rule', 'any'),
                    approvers=[{'type': 'user', 'ref': x} for x in a['approvers']],
                )
            ],
            note=rc.rule.name,
        )
        return {
            'target': str(task.id),
            'after': {'approval': str(approval.id)},
            'undo': {'kind': 'cancel_approval', 'id': str(approval.id)},
        }
    raise ClientException(
        detail=f'unknown action {kind}', extra={'code': 'invalid_rule'}
    )


async def _round_robin(
    session: DBAsyncScopedSession, scope: RequestScope, rc: RunContext, role: str
) -> str | None:
    """The member of ``role`` after the one this rule assigned last (alphabetical order)."""
    people = sorted(
        {
            u
            for u, r, _ in await grants_in([access.project_domain(rc.project.id)])
            if r == role
        }
    )
    if not people:
        return None
    last = None
    for run in await runs_of(session, rule_id=rc.rule.id, limit=50):
        for a in run.actions or []:
            if a.get('type') == 'assign' and a.get('after', {}).get('user_id'):
                last = a['after']['user_id']
                break
        if last:
            break
    if last in people:
        return people[(people.index(last) + 1) % len(people)]
    return people[0]


async def _insert_run(
    session: DBAsyncScopedSession, rc: RunContext, status: str, **values: Any
) -> UUID | None:
    """The run row of a live occurrence; ``None`` when this occurrence already ran (idempotency)."""
    row = await session.execute(
        pg_insert(Run)
        .values(
            tenant_id=rc.rule.tenant_id,
            organization_id=rc.rule.organization_id,
            rule_id=rc.rule.id,
            rule_version=rc.rule.version,
            occurrence_key=rc.occurrence[:200],
            event_id=rc.event.event_id if rc.event else None,
            subject_type='task' if rc.task else 'project',
            subject_id=str(rc.task.id if rc.task else rc.project.id),
            project_id=rc.project.id,
            depth=_depth.get(),
            mode='live',
            status=status,
            **values,
        )
        .on_conflict_do_nothing(
            index_elements=[Run.rule_id, Run.occurrence_key],
            index_where=Run.mode == 'live',
        )
        .returning(Run.id)
    )
    return row.scalar_one_or_none()


async def _execute(
    session: DBAsyncScopedSession, scope: RequestScope, rc: RunContext
) -> tuple[str, list[dict[str, Any]], str | None]:
    """The actions in order as ``scope``: ``(status, results, error)`` — a failure rolls every write back."""
    results: list[dict[str, Any]] = []
    depth_token = _depth.set(_depth.get() + 1)
    running_token = _running.set(_running.get() | {rc.rule.id})
    try:
        async with session.begin_nested():
            with events.acting_as(
                events.Actor('rule', str(rc.rule.id), rc.rule.name), 'rule'
            ):
                for i, a in enumerate(rc.rule.actions):
                    try:
                        results.append(
                            {
                                'type': a['type'],
                                'status': 'done',
                                **await _act(session, scope, rc, i, a),
                            }
                        )
                    except Exception as exc:
                        results.append(
                            {
                                'type': a['type'],
                                'status': 'failed',
                                'error': str(exc)[:300],
                            }
                        )
                        raise
        return 'succeeded', results, None
    except Exception as exc:  # noqa: BLE001 — the run records the failure, the triggering write goes on
        detail = getattr(exc, 'detail', None) or str(exc)
        return 'failed', results, str(detail)[:500]
    finally:
        _depth.reset(depth_token)
        _running.reset(running_token)


async def run_rule(
    session: DBAsyncScopedSession,
    rule: PpmAutomationRule,
    project: ews_models.Project,
    *,
    task: ews_models.Task | None,
    occurrence: str,
    event: events.Event | None = None,
    trigger_date: date | None = None,
    log_skipped: bool = True,
) -> None:
    """One live occurrence of a rule (idempotent on ``occurrence``)."""
    rc = RunContext(rule, project, task, occurrence, event, trigger_date)
    if _depth.get() >= MAX_DEPTH:
        await _insert_run(
            session, rc, 'loop_blocked', reason=f'automation depth {_depth.get()}'
        )
        return
    hour_ago = _now() - timedelta(hours=1)
    recent = await session.scalar(
        select(func.count(Run.id)).where(
            Run.rule_id == rule.id, Run.mode == 'live', Run.created_at >= hour_ago
        )
    )
    if (recent or 0) >= MAX_RUNS_PER_HOUR:
        await _insert_run(
            session,
            rc,
            'throttled',
            reason=f'more than {MAX_RUNS_PER_HOUR} runs in an hour',
        )
        return
    ctx = rules.Context(
        item=item_state(task) if task else {},
        project=await project_state(session, project),
        actor=event.actor.ref if event else None,
        changes=(event.changes or {}) if event else {},
    )
    ok, results = rules.evaluate(rule.conditions or [], ctx)
    if not ok:
        if log_skipped:
            await _insert_run(
                session, rc, 'skipped', conditions=results, reason='conditions not met'
            )
        return
    run_id = await _insert_run(session, rc, 'succeeded', conditions=results)
    if run_id is None:
        return
    started = clock.monotonic()
    owner = await scope_of(rule.owner, rule.organization_id, rule.owner_user_id)
    if owner is None:
        status, actions, error = (
            'failed',
            [],
            'the rule owner is no longer a member of the organization',
        )
    else:
        status, actions, error = await _execute(session, owner, rc)
    run = await session.get(Run, run_id)
    assert run is not None
    run.status, run.actions, run.reason = status, actions, error
    run.duration_ms = int((clock.monotonic() - started) * 1000)
    rule.last_run_at, rule.last_status = _now(), status
    rule.failures = 0 if status == 'succeeded' else rule.failures + 1
    if rule.failures >= FAILURES_TO_PAUSE and rule.status == 'active':
        await _pause(session, rule, error)
    await session.flush()


async def _pause(
    session: DBAsyncScopedSession, rule: PpmAutomationRule, error: str | None
) -> None:
    rule.status = 'paused'
    rule.next_run_at = None
    await _emit(
        session,
        None,
        rule,
        'ppm.automation_rule.paused',
        data={'failures': rule.failures, 'error': error},
        actor=events.Actor('system'),
        cause='rule',
    )
    await notify(
        session,
        tenant_id=rule.tenant_id,
        organization_id=rule.organization_id,
        kind='ppm:automation_failed',
        recipients=[rule.owner],
        title=f'Automation paused after {rule.failures} failed runs: {rule.name}',
        body=error or '',
        link='/ppm/automations',
        subject_type='automation_rule',
        subject_id=str(rule.id),
        project_id=rule.project_id,
        via='automation',
        occurrence=f'automation_paused:{rule.id}:{rule.version}:{rule.failures}',
        data={'rule': rule.name},
    )


@events.subscribe
async def on_event(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    """Event rules of the event's project (never for templates; a rule never reacts to its own run)."""
    if event.topic not in rules.EVENT_TOPICS or event.project_id is None:
        return
    candidates = list(
        (
            await session.scalars(
                select(Rule)
                .where(
                    Rule.project_id == event.project_id,
                    Rule.trigger_event == event.topic,
                    Rule.status == 'active',
                    Rule.deleted_at.is_(None),
                )
                .order_by(Rule.position, Rule.created_at)
            )
        ).all()
    )
    if not candidates:
        return
    project = await session.get(Project, event.project_id)
    if project is None or project.kind != 'project':
        return
    task = await _subject_task(session, event)
    state = item_state(task) if task else {}
    for rule in candidates:
        if rule.id in _running.get():
            continue
        if not rules.trigger_matches(rule.trigger, event.changes, state):
            continue
        if rule.item_types and (
            task is None or task.work_item_type not in rule.item_types
        ):
            continue
        await run_rule(
            session, rule, project, task=task, occurrence=event.event_id, event=event
        )


# --- relative and scheduled rules -----------------------------------------------------------------


def _open_items(project_id: UUID) -> Any:
    from . import _widgets as widgets  # shared counted / done conditions

    return select(Task).where(
        Task.project_id == project_id,
        Task.deleted_at.is_(None),
        widgets.counted_condition(),
        ~widgets.done_condition(),
    )


async def _relative_subjects(
    session: DBAsyncScopedSession, rule: PpmAutomationRule, now: datetime
) -> list[tuple[ews_models.Task, str]]:
    """Items matching a relative trigger with their occurrence key (``<item>:<date>``)."""
    day = now.date()
    midnight = datetime.combine(day, datetime.min.time())
    on, days = rule.trigger.get('on'), int(rule.trigger.get('days') or 0)
    q = _open_items(rule.project_id)
    if rule.item_types:
        q = q.where(Task.work_item_type.in_(rule.item_types))
    if on == 'due_in':
        start = midnight + timedelta(days=days)
        q = q.where(Task.due_date >= start, Task.due_date < start + timedelta(days=1))
    elif on == 'overdue_by':
        q = q.where(Task.due_date < midnight - timedelta(days=days))
    elif on == 'start_reached':
        q = q.where(
            Task.start_date.is_not(None), Task.start_date < midnight + timedelta(days=1)
        )
    elif on == 'no_activity':
        a = PpmAuditEvent
        last = (
            select(func.max(a.occurred_at))
            .where(a.subject_type == 'task', a.subject_id == cast(Task.id, String))
            .scalar_subquery()
        )
        q = q.where(last < now - timedelta(days=days))
    tasks = list((await session.scalars(q.limit(SCAN_LIMIT))).all())
    out = []
    for t in tasks:
        stamp = {
            'due_in': t.due_date,
            'overdue_by': t.due_date,
            'start_reached': t.start_date,
        }.get(on)
        key = (
            (stamp.date().isoformat() if stamp else day.isoformat())
            if on != 'no_activity'
            else day.isoformat()
        )
        out.append((t, f'{t.id}:{on}:{key}'))
    return out


async def _scan(
    session: DBAsyncScopedSession, rule: PpmAutomationRule, now: datetime
) -> int:
    project = await session.get(Project, rule.project_id)
    if project is None or project.deleted_at is not None or project.kind != 'project':
        return 0
    ran = 0
    if rule.trigger_type == 'relative':
        for task, occurrence in await _relative_subjects(session, rule, now):
            await run_rule(
                session,
                rule,
                project,
                task=task,
                occurrence=occurrence,
                trigger_date=now.date(),
                log_skipped=False,
            )
            ran += 1
        rule.next_run_at = now + RELATIVE_EVERY
    else:
        instant = (rule.next_run_at or now).isoformat()
        each = rule.trigger.get('for_each', 'none')
        if each == 'item':
            q = _open_items(project.id)
            if rule.item_types:
                q = q.where(Task.work_item_type.in_(rule.item_types))
            for task in (await session.scalars(q.limit(SCAN_LIMIT))).all():
                await run_rule(
                    session,
                    rule,
                    project,
                    task=task,
                    occurrence=f'{instant}:{task.id}',
                    trigger_date=now.date(),
                )
                ran += 1
        else:
            await run_rule(
                session,
                rule,
                project,
                task=None,
                occurrence=f'{instant}:{project.id}',
                trigger_date=now.date(),
            )
            ran += 1
        rule.next_run_at = rules.next_run(rule.trigger, now)
    await session.flush()
    return ran


async def tick(
    session: DBAsyncScopedSession,
    now: datetime | None = None,
    *,
    organization_id: UUID | None = None,
) -> int:
    """Job: relative / scheduled rules due (≤ ``TICK_RULES`` per run, each in a savepoint), run retention."""
    now = now or _now()
    q = select(Rule).where(
        Rule.status == 'active',
        Rule.deleted_at.is_(None),
        Rule.trigger_type.in_(('relative', 'schedule')),
        Rule.next_run_at <= now,
    )
    if organization_id:
        q = q.where(Rule.organization_id == organization_id)
    due = list(
        (await session.scalars(q.order_by(Rule.next_run_at).limit(TICK_RULES))).all()
    )
    capability: dict[UUID, bool] = {}
    ran = 0
    for rule in due:
        if rule.organization_id not in capability:
            row = await session.scalar(
                select(PpmSettings).where(
                    PpmSettings.organization_id == rule.organization_id
                )
            )
            capability[rule.organization_id] = _settings.capabilities_of(row).get(
                'automation', False
            )
        if not capability[rule.organization_id]:
            rule.next_run_at = now + RELATIVE_EVERY
            continue
        async with session.begin_nested():
            ran += await _scan(session, rule, now)
    await session.execute(
        delete(Run).where(Run.created_at < now - timedelta(days=RETENTION_DAYS))
    )
    return ran


register_job('ppm.automation_tick', 60, tick)


# --- test and undo --------------------------------------------------------------------------------


async def test_rule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    definition: dict[str, Any],
    task: ews_models.Task | None,
) -> dict[str, Any]:
    """Dry-run (Ppm-1749) on an item as the caller: conditions with results, actions with before → after; every write
    is rolled back."""
    rule = Rule(
        id=UUID(int=0),
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        project_id=project.id,
        name=str(definition.get('name') or 'Test'),
        owner=access.author(scope),
        version=0,
        failures=0,
        status='disabled',
        **_definition(definition),
    )
    ctx = rules.Context(
        item=item_state(task) if task else {},
        project=await project_state(session, project),
    )
    ok, results = rules.evaluate(rule.conditions or [], ctx)
    out: dict[str, Any] = {
        'matched': ok,
        'conditions': results,
        'actions': [],
        'status': 'dry_run',
    }
    if not ok:
        return out
    rc = RunContext(
        rule, project, task, f'test:{_now().isoformat()}', None, _now().date()
    )
    nested = await session.begin_nested()
    try:
        status, actions, error = await _execute(session, scope, rc)
    finally:
        await nested.rollback()
    out.update({'actions': actions, 'error': error, 'failed': status == 'failed'})
    return out


async def _restore_patch(before: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    patch, clear = {}, []
    for key, value in before.items():
        if value in (None, '', []) and key in (
            'user_id',
            'due_date',
            'estimated_minutes',
            'priority',
        ):
            clear.append(key)
        elif key == 'due_date' and isinstance(value, str) and len(value) == 10:
            patch[key] = f'{value}T00:00:00'
        else:
            patch[key] = value
    return patch, clear


async def undo(
    session: DBAsyncScopedSession, scope: RequestScope, run: PpmAutomationRun
) -> PpmAutomationRun:
    """Revert the run's reversible actions (newest first) when every target still holds the run's *after* values;
    409 ``undo_conflict`` lists the targets changed since."""
    if run.status != 'succeeded' or run.mode != 'live':
        raise ConflictException(
            detail='only a succeeded run can be undone', extra={'code': 'not_undoable'}
        )
    plan: list[tuple[dict[str, Any], Any]] = []
    conflicts: list[dict[str, Any]] = []
    for a in reversed(run.actions or []):
        u = a.get('undo')
        if not u:
            continue
        if u['kind'] == 'restore':
            task, project = await access.load_task(
                session, scope, a['target'], access.TASK, 'update'
            )
            if _fields(task, tuple(a['after'])) != a['after']:
                conflicts.append(
                    {
                        'type': a['type'],
                        'target': a['target'],
                        'now': _fields(task, tuple(a['after'])),
                    }
                )
            plan.append((a, (task, project)))
        elif u['kind'] == 'delete_item':
            task = await session.get(Task, UUID(u['id']))
            if task is None or task.deleted_at is not None:
                conflicts.append(
                    {'type': a['type'], 'target': u['id'], 'now': 'deleted'}
                )
            else:
                await access.require(scope, task.project_id, access.TASK, 'delete')
                plan.append((a, task))
        elif u['kind'] == 'cancel_approval':
            try:
                approval = await approvals.get(session, scope, u['id'])
            except NotFoundException:
                approval = None
            if approval is None or approval.status != 'pending':
                conflicts.append(
                    {
                        'type': a['type'],
                        'target': u['id'],
                        'now': getattr(approval, 'status', None),
                    }
                )
            else:
                plan.append((a, approval))
        elif u['kind'] == 'delete_checklist':
            plan.append((a, None))
    if conflicts:
        raise ConflictException(
            detail='the targets changed since the run',
            extra={'code': 'undo_conflict', 'conflicts': conflicts},
        )
    for a, target in plan:
        kind = a['undo']['kind']
        if kind == 'restore':
            task, project = target
            patch, clear = await _restore_patch(a['before'])
            await item_update.update_item(
                session, scope, task, project, {**patch, 'clear': clear}
            )
        elif kind == 'delete_item':
            target.deleted_at = _now()
            await items.delete_subtree(session, target)
            await session.flush()
            await items.refresh_rollups(session, target.parent_id)
            await events.emit(
                session,
                scope,
                'ppm.task.deleted',
                'task',
                target.id,
                project_id=target.project_id,
                data={'code': target.code, 'name': target.name, 'undo_of': str(run.id)},
            )
        elif kind == 'cancel_approval':
            await approvals.cancel(session, scope, target, 'automation run undone')
        elif kind == 'delete_checklist':
            task, _ = await access.load_task(
                session, scope, a['target'], access.TASK, 'update'
            )
            for item in await checklists.listing(session, task.id):
                if str(item.id) in a['undo'].get('ids', []):
                    await checklists.remove(session, scope, task, item)
    run.status = 'undone'
    run.undone_at = _now()
    run.undone_by = access.author(scope)
    await session.flush()
    return run


async def load_run(
    session: DBAsyncScopedSession, scope: RequestScope, run_id: str
) -> PpmAutomationRun:
    run = await session.scalar(
        select(Run).where(
            Run.id == access.parse_uuid(run_id, 'run'),
            Run.organization_id == scope.organization_id,
        )
    )
    if run is None or run.project_id is None:
        raise NotFoundException(detail='run not found')
    if not await is_allowed(
        scope, AUTOMATION, 'update', access.project_domains(scope, run.project_id)
    ):
        raise PermissionDeniedException(detail=f'{AUTOMATION}:update is required')
    return run
