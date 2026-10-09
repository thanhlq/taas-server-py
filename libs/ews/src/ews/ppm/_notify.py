"""PPM notifications = system automation rules (automation-spec Part A, Ppm-1754, ADR-17): the V1 kind catalog, the
in-process event subscriber that turns PPM events into ``ews.notifications.notify`` calls, and the scheduled
due-soon / overdue reminders (runner job, once a day per item thanks to ``dedup_key``).

Recipients = the kind's roles − the actor (Ppm-1702) − users who cannot read the project (members + inherited
admins; development sign-in: everybody). A project can switch kinds off (``settings.notifications.off``, Ppm-1713).
Titles are English (e-mail subject, fallback); the web renders ``kind`` + ``data`` in the reader's language.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import select, text

from ews.notifications import Kind, notify, register_job, register_kinds
from ews.security import RequestScope

from . import _events as events
from . import _work_items as items
from .controllers._task_support import task_watchers

log = logging.getLogger(__name__)

register_kinds(
    Kind('ppm:task_assigned', 'ppm', email='instant'),
    Kind('ppm:task_mentioned', 'ppm', email='instant', mandatory=True),
    Kind('ppm:task_commented', 'ppm', email='digest'),
    Kind('ppm:task_status_changed', 'ppm', email='digest'),
    Kind('ppm:task_due_soon', 'ppm', email='digest'),
    Kind('ppm:task_overdue', 'ppm', email='digest'),
    Kind('ppm:project_member_added', 'ppm', email='instant'),
    Kind('ppm:approval_requested', 'ppm', email='instant', mandatory=True),
    Kind('ppm:approval_decided', 'ppm', email='instant'),
)


def _link(
    org_slug: str | None, project_id: object, task_id: object | None = None
) -> str:
    base = (
        f'/{org_slug}/ppm/projects/{project_id}'
        if org_slug
        else f'/ppm/projects/{project_id}'
    )
    return f'{base}?task={task_id}' if task_id else base


def _kind_off(project: ews_models.Project | None, kind: str) -> bool:
    settings = (
        project.settings
        if project is not None and isinstance(project.settings, dict)
        else {}
    )
    off = (settings.get('notifications') or {}).get('off') or []
    return kind in off


async def _send(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    event: events.Event,
    project: ews_models.Project,
    *,
    kind: str,
    recipients: list[str],
    title: str,
    task: ews_models.Task | None = None,
    data: dict[str, Any] | None = None,
    exclude: list[str] | None = None,
) -> None:
    if _kind_off(project, kind) or not recipients:
        return
    from ._members import readers as member_readers  # late: members → access

    readers = await member_readers(session, scope, project)
    if readers is not None:
        recipients = [r for r in recipients if r.lower() in readers]
    actor = [event.actor.ref or '']
    if scope is not None:
        actor += [str(scope.user_id)]
    await notify(
        session,
        tenant_id=event.tenant_id,
        organization_id=event.organization_id,
        kind=kind,
        recipients=recipients,
        exclude=[*actor, *(exclude or [])],
        title=title,
        body=project.name,
        link=_link(
            scope.organization.slug if scope else None,
            project.id,
            task.id if task else None,
        ),
        subject_type='task' if task is not None else 'project',
        subject_id=str(task.id if task is not None else project.id),
        project_id=project.id,
        actor_ref=event.actor.ref,
        actor_name=event.actor.name,
        via='automation' if event.actor.type == 'rule' else 'user',
        occurrence=event.event_id,
        data={
            'code': task.code if task is not None else None,
            'name': task.name if task is not None else None,
            'project': project.name,
            **(data or {}),
        },
    )


def _who(event: events.Event) -> str:
    return event.actor.name or event.actor.ref or 'Someone'


async def _assignees(session: DBAsyncScopedSession, task: ews_models.Task) -> list[str]:
    collabs = await items.collaborators(session, [task.id])
    return [u for u in [task.user_id, *collabs.get(task.id, [])] if u]


@events.subscribe
async def on_ppm_event(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    """System rules of the V1 catalog (automation-spec Part A)."""
    if event.project_id is None:
        return
    project = await session.get(ews_models.Project, event.project_id)
    if project is None or project.kind == 'template':
        return  # templates notify nobody (Ppm-0880)
    if event.subject_type == 'approval':
        await _approval_event(session, scope, event, project)
        return
    task = (
        await session.get(ews_models.Task, UUID(event.subject_id))
        if event.subject_type == 'task'
        else None
    )
    label = (
        f'{task.code} {task.name}'.strip() if task is not None else project.name or ''
    )
    topic, data = event.topic, event.data or {}
    if topic == 'ppm.task.assigned' and task is not None:
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:task_assigned',
            task=task,
            recipients=[data.get('user') or ''],
            title=f'{_who(event)} assigned you {label}',
            data={'role': data.get('role')},
        )
    elif topic == 'ppm.task.mentioned' and task is not None:
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:task_mentioned',
            task=task,
            recipients=[data.get('user') or ''],
            title=f'{_who(event)} mentioned you on {label}',
            data={'comment_id': data.get('comment_id'), 'excerpt': data.get('excerpt')},
        )
    elif topic == 'ppm.comment.created' and task is not None:
        people = [*await _assignees(session, task), *task_watchers(task)]
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:task_commented',
            task=task,
            recipients=list(dict.fromkeys(people)),
            title=f'{_who(event)} commented on {label}',
            exclude=list(data.get('mentioned_user_ids') or []),
            data={'comment_id': data.get('comment_id'), 'excerpt': data.get('excerpt')},
        )
    elif task is not None and (
        topic == 'ppm.task.completed'
        or (topic == 'ppm.task.updated' and 'stage_id' in (event.changes or {}))
    ):
        if topic == 'ppm.task.updated' and 'completed_at' in (event.changes or {}):
            return  # the semantic ``completed`` / ``reopened`` event carries it
        people = [*task_watchers(task), task.requested_user_id or '']
        stage = (
            await session.get(ews_models.WorkflowStage, task.stage_id)
            if task.stage_id
            else None
        )
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:task_status_changed',
            task=task,
            recipients=list(dict.fromkeys(p for p in people if p)),
            title=f'{label} moved to {stage.name if stage else task.stage_type}',
            data={
                'stage': stage.name if stage else None,
                'stage_type': task.stage_type,
            },
        )
    elif topic == 'ppm.project.member_added':
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:project_member_added',
            recipients=[data.get('email') or data.get('user_id') or ''],
            title=f'{_who(event)} added you to {project.name}',
            data={'role': (event.changes or {}).get('role', {}).get('to')},
        )


async def _approval_event(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    event: events.Event,
    project: ews_models.Project,
) -> None:
    """Approvers are asked (mandatory in-app, Ppm-0873); the requester hears the outcome."""
    data = event.data or {}
    task = (
        await session.get(ews_models.Task, UUID(str(data['subject_id'])))
        if data.get('subject_type') == 'task' and data.get('subject_id')
        else None
    )
    title = str(data.get('title') or '')
    extra = {'approval_id': event.subject_id, 'subject_type': data.get('subject_type')}
    if event.topic == 'ppm.approval.requested':
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:approval_requested',
            task=task,
            recipients=[str(r) for r in data.get('approvers') or []],
            title=f'{_who(event)} asks for your approval: {title}',
            data=extra,
        )
    elif event.topic in (
        'ppm.approval.approved',
        'ppm.approval.rejected',
        'ppm.approval.changes_requested',
    ):
        decision = event.topic.rsplit('.', 1)[1]
        await _send(
            session,
            scope,
            event,
            project,
            kind='ppm:approval_decided',
            task=task,
            recipients=[str(data.get('requested_by') or '')],
            title=f'{title}: {decision.replace("_", " ")}',
            data={**extra, 'decision': decision, 'comment': data.get('comment')},
        )


async def due_reminders(
    session: DBAsyncScopedSession, today: datetime | None = None
) -> int:
    """``ppm:task_due_soon`` (due tomorrow) and ``ppm:task_overdue`` (due yesterday) for open items of live
    projects; one per item and day (``dedup_key``)."""
    day = (today or datetime.now(UTC)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    t, p = ews_models.Task, ews_models.Project
    sent = 0
    for kind, start in (
        ('ppm:task_due_soon', day + timedelta(days=1)),
        ('ppm:task_overdue', day - timedelta(days=1)),
    ):
        rows = await session.execute(
            select(t, p)
            .join(p, p.id == t.project_id)
            .where(
                t.deleted_at.is_(None),
                t.completed_at.is_(None),
                t.due_date >= start,
                t.due_date < start + timedelta(days=1),
                p.deleted_at.is_(None),
                p.kind != 'template',
            )
            .limit(2000)
        )
        for task, project in rows.all():
            if items.is_done(task) or _kind_off(project, kind):
                continue
            slug = await session.scalar(
                text('select slug from taas_organizations where id = :id'),
                {'id': project.organization_id},
            )
            label = f'{task.code} {task.name}'.strip()
            sent += await notify(
                session,
                tenant_id=project.tenant_id,
                organization_id=project.organization_id,
                kind=kind,
                recipients=await _assignees(session, task),
                title=f'{label} is due tomorrow'
                if kind.endswith('due_soon')
                else f'{label} is overdue',
                body=project.name,
                link=_link(slug, project.id, task.id),
                subject_type='task',
                subject_id=str(task.id),
                project_id=project.id,
                via='automation',
                occurrence=f'{kind.split(":")[1]}:{day.date().isoformat()}',
                data={
                    'code': task.code,
                    'name': task.name,
                    'project': project.name,
                    'due_date': task.due_date.isoformat(),
                },
            )
    return sent


register_job('ppm.due_reminders', 3600, due_reminders)
