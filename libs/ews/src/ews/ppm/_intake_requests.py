"""Intake requests (taas-specs/ppm/intake/intake-spec.md §5.1, §5.3, §5.4, Ppm-1115…1174, ADR-47): a request is a work
item of the form's queue project + its ``taas_ppm_requests`` record.

- **Submit** (internal or public, one transaction): form open, anti-abuse (public: honeypot, IP-hash limits),
  idempotency per form, answers (``_intake_forms.clean_answers``), routing (first match, as the form owner), the item
  through ``_work_items.create_item`` (as the form owner, actor = requester), the record, ``ppm.request.submitted``,
  notifications (triagers; member requester in-app; external requester e-mail with the tracking link).
- **Triage** (``ppm.request:triage`` on the queue): accept as item · in place · as project, reject, merge duplicate,
  ask for info; conversation = item comments (``privacy = 'requester'`` for requester-visible replies).
- **Status** (§5.4) mirrors the request item before a decision and the result item / project after it (subscriber);
  every change emits ``ppm.request.status_changed`` and notifies the requester.
- **Requester**: *mine* (members, by ref) and the public tracking token (only its SHA-256 is stored)."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.core import Organization
from db.models.ppm import PpmForm, PpmRequest
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
    TooManyRequestsException,
)
from sqlalchemy import func, or_, select

from ews.notifications import Kind, notify, register_kinds
from ews.security import RequestScope, is_allowed, scope_of
from ews.shared import (
    ConflictException,
    html_to_text,
    parse_uuid,
    random_token,
    token_hash,
)

from . import _access as access
from . import _events as events
from . import _intake as intake
from . import _intake_forms as forms
from . import _item_types as item_types
from . import _work_items as items
from .workflow_catalog import stage_type_info

log = logging.getLogger(__name__)

STATUSES = (
    'submitted',
    'in_review',
    'needs_info',
    'accepted',
    'in_progress',
    'done',
    'rejected',
    'duplicate',
    'withdrawn',
    'cancelled',
)
OPEN = intake.OPEN_STATUSES
FINAL = ('rejected', 'duplicate', 'withdrawn')
CLOSED = ('done', 'rejected', 'duplicate', 'withdrawn', 'cancelled')
ACCEPT_MODES = ('item', 'in_place', 'project')
PER_IP_MINUTE, PER_IP_DAY, PER_FORM_DAY = 5, 50, 1000
TRACKING_DAYS = 180
REQUESTER = 'requester'
Comment = ews_models.ProjectComment
Task = ews_models.Task

register_kinds(
    Kind('ppm:request_submitted', 'ppm', email='instant'),
    Kind('ppm:request_update', 'ppm', email='instant', mandatory=True),
    Kind('ppm:request_reply', 'ppm', email='instant'),
)


def _error(detail: str, code: str, **extra: Any) -> ClientException:
    return ClientException(detail=detail, extra={'code': code, **extra})


def _conflict(detail: str, code: str) -> ConflictException:
    return ConflictException(detail=detail, extra={'code': code})


@dataclass(slots=True)
class Requester:
    ref: str | None
    """A member's user ref (e-mail); ``None`` for an external requester."""
    name: str | None
    email: str | None
    is_member: bool
    locale: str | None = None
    user_id: UUID | None = None

    @property
    def label(self) -> str:
        return self.name or self.email or self.ref or 'Requester'


@dataclass(slots=True)
class Submitted:
    request: PpmRequest
    task: ews_models.Task
    token: str | None = None
    replay: bool = False


# --- submit ------------------------------------------------------------------------------------------------------


def _check_limits_args(ip_hash: str | None) -> list[tuple[Any, int, timedelta]]:
    if not ip_hash:
        return []
    return [
        (PpmRequest.ip_hash == ip_hash, PER_IP_MINUTE, timedelta(minutes=1)),
        (PpmRequest.ip_hash == ip_hash, PER_IP_DAY, timedelta(days=1)),
    ]


async def _check_limits(
    session: DBAsyncScopedSession, form: PpmForm, ip_hash: str | None
) -> None:
    """§5.6: per form and IP hash 5 / minute and 50 / day, per form 1 000 / day (429)."""
    now = datetime.now(UTC)
    checks = [
        *_check_limits_args(ip_hash),
        (PpmRequest.form_id == form.id, PER_FORM_DAY, timedelta(days=1)),
    ]
    for condition, limit, window in checks:
        count = await session.scalar(
            select(func.count()).where(
                PpmRequest.form_id == form.id,
                condition,
                PpmRequest.submitted_at >= now - window,
            )
        )
        if (count or 0) >= limit:
            raise TooManyRequestsException(
                detail='too many requests, try again later',
                extra={
                    'code': 'rate_limited',
                    'retry_after': int(window.total_seconds()),
                },
            )


async def _definition(
    session: DBAsyncScopedSession, form: PpmForm, version: int | None
) -> tuple[int, dict[str, Any]]:
    """The version the requester filled (if it exists), else the latest; 409 ``form_closed`` when not published."""
    if form.status != 'published' or not form.current_version:
        raise _conflict('this form does not accept requests', 'form_closed')
    if version and 0 < version <= form.current_version:
        found = await intake.version_of(session, form.id, version)
        if found is not None:
            return found.version, found.definition
    latest = await intake.latest_version(session, form)
    if latest is None:
        raise _conflict('this form does not accept requests', 'form_closed')
    return latest.version, latest.definition


async def _queue(
    session: DBAsyncScopedSession, owner: RequestScope, project_id: object
) -> ews_models.Project | None:
    """The queue project if the form owner may create items there, else ``None``."""
    try:
        project = await access.load_project(
            session, owner, project_id, access.TASK, 'create'
        )
    except NotFoundException, PermissionDeniedException, ClientException:
        return None
    return project if project.kind == 'project' else None


async def _request_type(session: DBAsyncScopedSession, form: PpmForm) -> str | None:
    if form.request_type_key:
        return form.request_type_key
    for row in await item_types.library(session, form.tenant_id, form.organization_id):
        if row.behaviour == 'request' and not getattr(row, 'archived_at', None):
            return row.key
    return None


@dataclass(slots=True)
class Routed:
    queue: ews_models.Project
    fields: dict[str, Any]
    accept_in_place: bool
    trace: list[dict[str, Any]]


async def _apply_routing(
    session: DBAsyncScopedSession,
    owner: RequestScope,
    form: PpmForm,
    queue: ews_models.Project,
    mapped: dict[str, Any],
    actions: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> Routed:
    """§5.3: apply the matched actions in order (later *set* actions win; the queue comes from the first one that sets
    it); an invalid action is skipped and recorded on its rule in the trace."""
    fields = dict(mapped)
    in_place = False
    queue_set = False
    state = dict((form.settings or {}).get('routing_state') or {})
    outcomes: dict[int, list[dict[str, Any]]] = {}

    def record(a: dict[str, Any], status: str, reason: str | None = None) -> None:
        outcomes.setdefault(int(a.get('rule', 0)), []).append(
            {
                'type': a.get('type'),
                'status': status,
                **({'reason': reason} if reason else {}),
            }
        )

    for a in actions:
        kind = a.get('type')
        if kind == 'set_queue':
            if queue_set:
                record(a, 'skipped', 'queue already set by an earlier rule')
                continue
            target = (
                await _queue(session, owner, a.get('project_id'))
                if a.get('project_id')
                else None
            )
            if target is None:
                record(
                    a, 'skipped', 'the form owner cannot create items in this project'
                )
                continue
            queue, queue_set = target, True
        elif kind == 'set_priority':
            try:
                fields['priority'] = max(0, min(5, int(a.get('value'))))
            except TypeError, ValueError:
                record(a, 'skipped', 'invalid priority')
                continue
        elif kind == 'assign':
            to = str(a.get('to') or '').strip().lower()
            if '@' not in to:
                record(a, 'skipped', 'invalid user')
                continue
            fields['owner'] = to
        elif kind == 'assign_round_robin':
            users = [
                str(u).strip().lower()
                for u in a.get('users') or []
                if isinstance(u, str) and '@' in u
            ]
            if not users:
                record(a, 'skipped', 'no users')
                continue
            key = str(a.get('rule', 0))
            cursor = int(state.get(key) or 0)
            fields['owner'] = users[cursor % len(users)]
            state[key] = (cursor + 1) % len(users)
        elif kind == 'set_due':
            fields['due_date'] = forms.due_from(a)
        elif kind == 'add_labels':
            labels = [str(x).strip() for x in a.get('labels') or [] if str(x).strip()]
            fields['labels'] = list(
                dict.fromkeys([*(fields.get('labels') or []), *labels])
            )
        elif kind == 'accept_in_place':
            in_place = True
        else:
            record(a, 'skipped', 'unknown action')
            continue
        record(a, 'applied')
    if state != ((form.settings or {}).get('routing_state') or {}):
        form.settings = {**(form.settings or {}), 'routing_state': state}
    for entry in trace:
        if entry['rule'] in outcomes:
            entry['actions'] = outcomes[entry['rule']]
    return Routed(queue, fields, in_place, trace)


def _summary(definition: dict[str, Any], answers: dict[str, Any]) -> str:
    """Plain-text answers (the item description when no field maps to it)."""
    lines = []
    for f in definition.get('fields') or []:
        if isinstance(f, dict) and f.get('key') in answers:
            lines.append(
                f'{f.get("label") or f["key"]}: {forms.text_of(f, answers[f["key"]])}'
            )
    return '\n'.join(lines)


def _day(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value)[:19])


async def submit(
    session: DBAsyncScopedSession,
    form: PpmForm,
    requester: Requester,
    raw_answers: Any,
    *,
    form_version: int | None = None,
    idempotency_key: str | None = None,
    ip_hash: str | None = None,
) -> Submitted:
    """§5.1 steps 1 and 3–7 (the caller checked the audience, the honeypot and the permission)."""
    key = (idempotency_key or '').strip()[:64] or None
    if key:
        first = await session.scalar(
            select(PpmRequest).where(
                PpmRequest.form_id == form.id, PpmRequest.idempotency_key == key
            )
        )
        if first is not None:
            task = await session.get(Task, first.task_id)
            if task is not None:
                return Submitted(first, task, replay=True)
    version, definition = await _definition(session, form, form_version)
    if not requester.is_member:
        await _check_limits(session, form, ip_hash)
    answers, errors = forms.clean_answers(definition, raw_answers, member=requester.ref)
    if errors:
        raise _error(
            'some answers are missing or invalid', 'invalid_answers', errors=errors
        )
    owner = await scope_of(form.owner, form.organization_id, form.owner_user_id)
    queue = (
        await _queue(session, owner, form.queue_project_id)
        if owner and form.queue_project_id
        else None
    )
    if owner is None or queue is None:
        raise _conflict('this form cannot receive requests now', 'form_unavailable')
    if any(
        a.get('type') == 'assign_round_robin'
        for r in definition.get('routing') or []
        for a in r.get('actions') or []
    ):
        await session.refresh(form, with_for_update=True)
    actions, trace = forms.route(
        definition,
        answers,
        forms.requester_facts(requester.email or requester.ref, requester.is_member),
    )
    routed = await _apply_routing(
        session, owner, form, queue, forms.mapped(definition, answers), actions, trace
    )
    n = (
        await session.scalar(select(func.count()).where(PpmRequest.form_id == form.id))
        or 0
    ) + 1
    fields = routed.fields
    name = fields.get('name') or forms.title(
        definition, answers, form=form.name, requester=requester.label, n=n
    )
    new = items.NewItem(
        name=name,
        description=fields.get('description') or _summary(definition, answers) or None,
        work_item_type=await _request_type(session, form),
        requested_user_id=requester.ref,
        owner=fields.get('owner'),
        labels=fields.get('labels'),
        priority=fields.get('priority'),
        start_date=_day(fields.get('start_date')),
        due_date=_day(fields.get('due_date')),
        estimated_minutes=fields.get('estimated_minutes'),
        cause='intake',
    )
    actor = events.Actor(
        'user' if requester.is_member else REQUESTER,
        requester.ref or requester.email,
        requester.name,
    )
    with events.acting_as(actor, 'intake'):
        try:
            async with session.begin_nested():
                task = await items.create_item(session, owner, routed.queue, new)
        except (
            ClientException
        ):  # the request type is not allowed in this queue's process: default type
            new.work_item_type = None
            task = await items.create_item(session, owner, routed.queue, new)
        if fields.get('custom_fields'):
            await _custom_fields(
                session, owner, routed.queue, task, fields['custom_fields'], trace
            )
    token = random_token() if not requester.is_member else None
    now = datetime.now(UTC)
    request = PpmRequest(
        tenant_id=form.tenant_id,
        organization_id=form.organization_id,
        task_id=task.id,
        form_id=form.id,
        form_version=version,
        requester_ref=requester.ref,
        requester_name=(requester.name or '')[:200] or None,
        requester_email=(requester.email or '').lower()[:320] or None,
        is_member=requester.is_member,
        requester_locale=requester.locale,
        answers=answers,
        status='submitted',
        routing_trace=routed.trace,
        tracking_hash=token_hash(token) if token else None,
        idempotency_key=key,
        ip_hash=ip_hash,
        submitted_at=now,
    )
    session.add(request)
    await session.flush()
    if routed.accept_in_place:
        request.decision = 'accepted_in_place'
        request.decided_by = form.owner
        request.decided_at = now
        request.result_task_id = task.id
        request.status = _mirrored(request, task, None) or 'accepted'
    with events.acting_as(actor, 'intake'):
        await events.emit(
            session,
            owner,
            'ppm.request.submitted',
            'task',
            task.id,
            project_id=task.project_id,
            data={
                'form_id': str(form.id),
                'form': form.name,
                'version': version,
                'code': task.code,
                'requester_kind': 'member' if requester.is_member else 'external',
                'priority': task.priority,
                'routing': [t['name'] for t in routed.trace if t['matched']],
            },
        )
    await _notify_submitted(session, owner, form, request, task, token)
    return Submitted(request, task, token)


async def _custom_fields(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task,
    values: dict[str, Any],
    trace: list[dict[str, Any]],
) -> None:
    from . import (
        _custom_fields as custom_fields,
    )  # custom fields → work items: imported late

    try:
        async with session.begin_nested():
            await custom_fields.set_values(session, scope, project, task, values)
    except ClientException as error:
        trace.append(
            {
                'rule': -1,
                'name': 'custom fields',
                'matched': False,
                'error': str(error.detail)[:300],
            }
        )


# --- status ------------------------------------------------------------------------------------------------------

_PROJECT_ACCEPTED = {'New', 'Draft', 'Planned', 'Approved', 'Pending Approval'}
_PROJECT_DONE = {'Completed', 'Archived'}
_PROJECT_CANCELLED = {'Cancelled', 'Rejected'}


def _band(stage_type: str | None) -> str:
    if stage_type in ('cancelled', 'rejected'):
        return 'cancelled'
    info = stage_type_info(stage_type)
    return info.band if info is not None else 'initial'


def _mirrored(
    r: PpmRequest, task: ews_models.Task | None, project: ews_models.Project | None
) -> str | None:
    """§5.4 status from the request item (no decision) or the result (accepted); ``None`` = keep."""
    if r.status in FINAL:
        return None
    if r.decision is None:
        if task is not None and task.deleted_at is not None:
            return 'cancelled'
        if r.status == 'needs_info' or task is None:
            return None
        return 'submitted' if _band(task.stage_type) == 'initial' else 'in_review'
    if r.decision == 'accepted_project':
        if project is None or project.deleted_at is not None:
            return 'cancelled'
        status = str(project.status or '')
        if status in _PROJECT_DONE:
            return 'done'
        if status in _PROJECT_CANCELLED:
            return 'cancelled'
        return 'accepted' if status in _PROJECT_ACCEPTED else 'in_progress'
    if task is None or task.deleted_at is not None:
        return 'cancelled'
    band = _band(task.stage_type)
    return {'initial': 'accepted', 'done': 'done', 'cancelled': 'cancelled'}.get(
        band, 'in_progress'
    )


async def set_status(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    r: PpmRequest,
    status: str,
    *,
    message: str | None = None,
) -> None:
    """Change the requester-facing status: ``ppm.request.status_changed`` + requester notification."""
    if status == r.status:
        return
    before, r.status = r.status, status
    r.closed_at = datetime.now(UTC) if status in CLOSED else None
    await session.flush()
    task = await session.get(Task, r.task_id)
    await events.emit(
        session,
        scope,
        'ppm.request.status_changed',
        'task',
        r.task_id,
        project_id=task.project_id if task else None,
        tenant_id=r.tenant_id,
        organization_id=r.organization_id,
        changes={'request_status': {'from': before, 'to': status}},
    )
    await _notify_requester(session, r, task, f'status_{status}', message)


async def mirror(
    session: DBAsyncScopedSession, scope: RequestScope | None, r: PpmRequest
) -> None:
    result_id = (
        r.result_task_id
        if r.decision in ('accepted_item', 'accepted_in_place')
        else r.task_id
    )
    task = await session.get(Task, result_id) if result_id else None
    project = (
        await session.get(ews_models.Project, r.result_project_id)
        if r.decision == 'accepted_project' and r.result_project_id
        else None
    )
    status = _mirrored(r, task, project)
    if status:
        await set_status(session, scope, r, status)


_TASK_TOPICS = (
    'ppm.task.updated',
    'ppm.task.completed',
    'ppm.task.reopened',
    'ppm.task.deleted',
    'ppm.task.moved',
)
_PROJECT_TOPICS = ('ppm.project.updated', 'ppm.project.deleted', 'ppm.project.archived')


@events.subscribe
async def on_event(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    """Status mirroring (§5.4) on item / project changes."""
    if event.topic in _TASK_TOPICS and event.subject_type == 'task':
        task_id = parse_uuid(event.subject_id, 'task', not_found=False)
        rows = await session.scalars(
            select(PpmRequest).where(
                or_(
                    PpmRequest.task_id == task_id, PpmRequest.result_task_id == task_id
                ),
                PpmRequest.status.notin_(FINAL),
            )
        )
    elif event.topic in _PROJECT_TOPICS and event.project_id is not None:
        rows = await session.scalars(
            select(PpmRequest).where(
                PpmRequest.result_project_id == event.project_id,
                PpmRequest.status.notin_(FINAL),
            )
        )
    else:
        return
    for r in list(rows):
        await mirror(session, scope, r)


# --- notifications -----------------------------------------------------------------------------------------------


async def _org_slug(session: DBAsyncScopedSession, organization_id: UUID) -> str | None:
    return await session.scalar(
        select(Organization.slug).where(Organization.id == organization_id)
    )


def request_link(slug: str | None, task_id: object) -> str:
    return (
        f'/{slug}/ppm/requests?id={task_id}' if slug else f'/ppm/requests?id={task_id}'
    )


def tracking_link(token: str) -> str:
    return f'/public/requests/{token}'


def _triagers(form: PpmForm | None) -> list[str]:
    if form is None:
        return []
    return list((form.settings or {}).get('triagers') or []) or [form.owner]


async def _notify_submitted(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    form: PpmForm,
    r: PpmRequest,
    task: ews_models.Task,
    token: str | None,
) -> None:
    slug = await _org_slug(session, form.organization_id)
    title = f'{task.code} {task.name}'.strip()
    await notify(
        session,
        tenant_id=form.tenant_id,
        organization_id=form.organization_id,
        kind='ppm:request_submitted',
        recipients=_triagers(form),
        exclude=[r.requester_ref or ''],
        title=f'New request: {title}',
        body=f'{form.name} · {r.requester_name or r.requester_email or r.requester_ref or ""}',
        link=request_link(slug, task.id),
        subject_type='task',
        subject_id=str(task.id),
        project_id=task.project_id,
        actor_ref=r.requester_ref or r.requester_email,
        actor_name=r.requester_name,
        occurrence=f'submitted:{r.id}',
    )
    if r.is_member and r.requester_ref:
        await _notify_requester(session, r, task, 'received', None, slug=slug)
    elif (
        token
        and r.requester_email
        and (form.settings or {}).get('notify_requester', True)
    ):
        await _confirmation_email(form, r, task, token)


async def _notify_requester(
    session: DBAsyncScopedSession,
    r: PpmRequest,
    task: ews_models.Task | None,
    what: str,
    message: str | None,
    *,
    slug: str | None = None,
) -> None:
    """In-app + e-mail to a member requester, e-mail to an external one (no link: the token is not stored)."""
    form = await session.get(PpmForm, r.form_id)
    if form is not None and not (form.settings or {}).get('notify_requester', True):
        return
    recipient = r.requester_ref if r.is_member else r.requester_email
    if not recipient:
        return
    code = task.code if task is not None else ''
    texts = {
        'received': f'Request {code} received',
        'reply': f'New reply on your request {code}',
        'status_needs_info': f'More information needed on your request {code}',
        'status_rejected': f'Your request {code} was declined',
        'status_duplicate': f'Your request {code} was merged with another request',
        'status_accepted': f'Your request {code} was accepted',
        'status_in_progress': f'Your request {code} is in progress',
        'status_done': f'Your request {code} is done',
        'status_cancelled': f'Your request {code} was cancelled',
        'status_in_review': f'Your request {code} is being reviewed',
        'status_withdrawn': f'Your request {code} was withdrawn',
    }
    if what not in texts:
        return
    link = None
    if r.is_member:
        slug = slug or await _org_slug(session, r.organization_id)
        link = f'/{slug}/ppm/requests?tab=mine&id={r.task_id}' if slug else None
    await notify(
        session,
        tenant_id=r.tenant_id,
        organization_id=r.organization_id,
        kind='ppm:request_update',
        recipients=[recipient],
        title=texts[what],
        body=(message or '')[:2000] or (task.name if task is not None else None),
        link=link,
        subject_type='task',
        subject_id=str(r.task_id),
        project_id=task.project_id if task is not None else None,
        occurrence=f'{what}:{r.task_id}:{datetime.now(UTC).isoformat()}',
    )


async def _confirmation_email(
    form: PpmForm, r: PpmRequest, task: ews_models.Task, token: str
) -> None:
    """Ppm-1170: the external requester's confirmation with the tracking link — sent directly (best effort) so the
    token is never stored."""
    try:
        from foundation.email.factory import EmailServiceFactory
        from foundation.email.types import EmailMultiAlternatives

        from ews.notifications._delivery import link_url

        url = link_url(tracking_link(token)) or tracking_link(token)
        rows = ''.join(
            f'<tr><th align="left" style="padding:4px 12px 4px 0">{html.escape(k)}</th>'
            f'<td style="padding:4px 0;white-space:pre-wrap">{html.escape(v)}</td></tr>'
            for k, v in _answer_lines(form, r)
        )
        body = (
            f'<p>We received your request <b>{html.escape(task.code or "")}</b> — {html.escape(form.name)}.</p>'
            f'<table>{rows}</table><p><a href="{html.escape(url)}">Follow your request</a></p>'
        )
        text = f'We received your request {task.code} — {form.name}.\n\nFollow your request: {url}'
        await EmailServiceFactory.get_email_service().send_message(
            EmailMultiAlternatives(
                subject=f'Request {task.code} received',
                body=text,
                html_body=body,
                to=[r.requester_email],
            )
        )
    except Exception as error:  # noqa: BLE001 - the request is stored; the confirmation screen shows the link too
        log.warning('intake confirmation e-mail failed: %s', error)


def _answer_lines(form: PpmForm, r: PpmRequest) -> list[tuple[str, str]]:
    fields = {
        f.get('key'): f
        for f in (form.draft or {}).get('fields') or []
        if isinstance(f, dict)
    }
    return [
        (str(fields.get(k, {}).get('label') or k), forms.text_of(fields.get(k, {}), v))
        for k, v in (r.answers or {}).items()
    ]


# --- reading -----------------------------------------------------------------------------------------------------


async def triage_projects(
    session: DBAsyncScopedSession, scope: RequestScope
) -> set[UUID]:
    """Queue projects of the organization's requests where the caller may triage."""
    ids = set(
        await session.scalars(
            select(Task.project_id)
            .join(PpmRequest, PpmRequest.task_id == Task.id)
            .where(
                PpmRequest.organization_id == scope.organization_id,
                PpmRequest.tenant_id == scope.tenant_id,
            )
            .distinct()
        )
    )
    out = set()
    for pid in ids:
        if pid and await is_allowed(
            scope, intake.REQUEST, 'triage', access.project_domains(scope, pid)
        ):
            out.add(pid)
    return out


def _requester_out(r: PpmRequest) -> dict[str, Any]:
    return {
        'ref': r.requester_ref,
        'name': r.requester_name,
        'email': r.requester_email or r.requester_ref,
        'is_member': r.is_member,
    }


async def _names(
    session: DBAsyncScopedSession, rows: list[tuple[PpmRequest, ews_models.Task]]
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    form_ids = {r.form_id for r, _ in rows}
    project_ids = {t.project_id for _, t in rows if t.project_id}
    forms_ = (
        dict(
            (
                await session.execute(
                    select(PpmForm.id, PpmForm.name).where(PpmForm.id.in_(form_ids))
                )
            )
            .tuples()
            .all()
        )
        if form_ids
        else {}
    )
    P = ews_models.Project
    projects = (
        dict(
            (await session.execute(select(P.id, P.name).where(P.id.in_(project_ids))))
            .tuples()
            .all()
        )
        if project_ids
        else {}
    )
    return forms_, projects


def _row(
    r: PpmRequest,
    t: ews_models.Task,
    form_names: dict[UUID, str],
    projects: dict[UUID, str],
    *,
    triager: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        'id': str(t.id),
        'code': t.code,
        'title': t.name,
        'form_id': str(r.form_id),
        'form_name': form_names.get(r.form_id, ''),
        'status': r.status,
        'priority': t.priority,
        'requester': _requester_out(r),
        'submitted_at': r.submitted_at,
        'updated_at': r.updated_at,
        'decision': r.decision,
        'closed_at': r.closed_at,
    }
    if triager:
        out |= {
            'queue_project_id': str(t.project_id),
            'queue_project_name': projects.get(t.project_id, ''),
            'owner': t.user_id,
            'due_date': t.due_date,
            'result_project_id': str(r.result_project_id)
            if r.result_project_id
            else None,
            'result_task_id': str(r.result_task_id) if r.result_task_id else None,
        }
    return out


async def listing(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    tab: str = 'inbox',
    form_id: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Inbox (open requests of queues I triage) · all (every request of those queues) · mine (as requester)."""
    from . import _settings as ppm_settings

    await ppm_settings.require_capability(session, scope, intake.CAPABILITY)
    stmt = (
        select(PpmRequest, Task)
        .join(Task, Task.id == PpmRequest.task_id)
        .where(
            PpmRequest.tenant_id == scope.tenant_id,
            PpmRequest.organization_id == scope.organization_id,
            Task.deleted_at.is_(None),
        )
    )
    triager = tab != 'mine'
    if tab == 'mine':
        stmt = stmt.where(PpmRequest.requester_ref == access.author(scope))
    else:
        queues = await triage_projects(session, scope)
        stmt = stmt.where(Task.project_id.in_(queues or {UUID(int=0)}))
        if tab == 'inbox' and not status:
            stmt = stmt.where(PpmRequest.status.in_(OPEN))
    if form_id:
        stmt = stmt.where(
            PpmRequest.form_id == parse_uuid(form_id, 'form', not_found=False)
        )
    if status == 'open':
        stmt = stmt.where(PpmRequest.status.in_(OPEN))
    elif status == 'closed':
        stmt = stmt.where(PpmRequest.status.in_(CLOSED))
    elif status:
        stmt = stmt.where(PpmRequest.status == status)
    if q and q.strip():
        like = f'%{q.strip()}%'
        stmt = stmt.where(
            or_(
                Task.name.ilike(like),
                Task.code.ilike(like),
                PpmRequest.requester_name.ilike(like),
                PpmRequest.requester_email.ilike(like),
                PpmRequest.requester_ref.ilike(like),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        (
            await session.execute(
                stmt.order_by(PpmRequest.submitted_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        ).tuples()
    )
    form_names, projects = await _names(session, rows)
    return [_row(r, t, form_names, projects, triager=triager) for r, t in rows], total


@dataclass(slots=True)
class Loaded:
    request: PpmRequest
    task: ews_models.Task
    project: ews_models.Project
    triager: bool
    requester: bool


async def load(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    request_id: object,
    *,
    triage: bool = False,
) -> Loaded:
    """A request the caller triages or requested (404 otherwise); ``triage`` = 403 for a requester."""
    task_id = parse_uuid(request_id, 'request')
    found = (
        await session.execute(
            select(PpmRequest, Task)
            .join(Task, Task.id == PpmRequest.task_id)
            .where(
                PpmRequest.task_id == task_id,
                PpmRequest.tenant_id == scope.tenant_id,
                PpmRequest.organization_id == scope.organization_id,
                Task.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise NotFoundException(detail='request not found')
    r, t = found
    project = await session.get(ews_models.Project, t.project_id)
    triager = project is not None and await is_allowed(
        scope, intake.REQUEST, 'triage', access.project_domains(scope, t.project_id)
    )
    mine = bool(r.requester_ref) and r.requester_ref == access.author(scope)
    if project is None or not (triager or mine):
        raise NotFoundException(detail='request not found')
    if triage and not triager:
        raise PermissionDeniedException(
            detail=f'missing permission {intake.REQUEST}:triage'
        )
    return Loaded(r, t, project, triager, mine)


def _answers_out(
    definition: dict[str, Any], answers: dict[str, Any]
) -> list[dict[str, Any]]:
    out = []
    for f in definition.get('fields') or []:
        if isinstance(f, dict) and f.get('key') in answers:
            out.append(
                {
                    'key': f['key'],
                    'label': f.get('label') or f['key'],
                    'type': f.get('type'),
                    'value': answers[f['key']],
                    'text': forms.text_of(f, answers[f['key']]),
                }
            )
    return out


async def conversation(
    session: DBAsyncScopedSession, r: PpmRequest, *, internal: bool
) -> list[dict[str, Any]]:
    """Requester-visible replies (+ internal notes and authors for triagers), oldest first."""
    from .controllers._task_support import uuid7_time

    stmt = select(Comment).where(
        Comment.object_type == 'task',
        Comment.object_id == str(r.task_id),
        Comment.deleted_at.is_(None),
    )
    if not internal:
        stmt = stmt.where(Comment.privacy == REQUESTER)
    requester = {x.lower() for x in (r.requester_ref, r.requester_email) if x}
    out = []
    for c in await session.scalars(stmt.order_by(Comment.id)):
        from_requester = (
            c.privacy == REQUESTER and (c.user_id or '').lower() in requester
        )
        out.append(
            {
                'id': str(c.id),
                'visibility': 'requester' if c.privacy == REQUESTER else 'internal',
                'author': c.user_id if internal else None,
                'from_requester': from_requester,
                'text': c.comment_text or html_to_text(c.html_text or ''),
                'created_at': uuid7_time(c.id),
            }
        )
    return out


async def timeline(
    session: DBAsyncScopedSession, task_id: UUID
) -> list[dict[str, Any]]:
    from db.models.ppm import PpmAuditEvent

    rows = await session.scalars(
        select(PpmAuditEvent)
        .where(
            PpmAuditEvent.subject_type == 'task',
            PpmAuditEvent.subject_id == str(task_id),
            PpmAuditEvent.event.in_(
                ('ppm.request.submitted', 'ppm.request.status_changed')
            ),
        )
        .order_by(PpmAuditEvent.occurred_at)
    )
    out = []
    for e in rows:
        status = (
            'submitted'
            if e.event == 'ppm.request.submitted'
            else ((e.changes or {}).get('request_status') or {}).get('to')
        )
        if status:
            out.append({'status': status, 'at': e.occurred_at})
    return out


async def detail(
    session: DBAsyncScopedSession, scope: RequestScope, loaded: Loaded
) -> dict[str, Any]:
    r, t = loaded.request, loaded.task
    version = await intake.version_of(session, r.form_id, r.form_version)
    form_names, projects = await _names(session, [(r, t)])
    out = _row(r, t, form_names, projects, triager=loaded.triager)
    out |= {
        'form_version': r.form_version,
        'answers': _answers_out(version.definition if version else {}, r.answers or {}),
        'conversation': await conversation(session, r, internal=loaded.triager),
        'timeline': await timeline(session, t.id),
        'can_triage': loaded.triager,
        'is_requester': loaded.requester,
        'can_withdraw': loaded.requester and r.status in OPEN,
    }
    if loaded.triager and r.result_task_id and r.result_task_id != t.id:
        result = await session.get(Task, r.result_task_id)
        out['result_item_project_id'] = (
            str(result.project_id) if result is not None else None
        )
    if loaded.triager:
        out |= {
            'description': t.description,
            'routing_trace': r.routing_trace or [],
            'decision_reason': r.decision_reason,
            'decided_by': r.decided_by,
            'decided_at': r.decided_at,
            'duplicate_of': str(r.duplicate_of) if r.duplicate_of else None,
        }
    elif r.status in ('rejected',):
        out['decision_reason'] = r.decision_reason
    return out


# --- triage ------------------------------------------------------------------------------------------------------


def _require_open(r: PpmRequest) -> None:
    if r.status not in OPEN:
        raise _conflict('this request was already decided', 'already_decided')


def _decide(
    r: PpmRequest, scope: RequestScope, decision: str, reason: str | None = None
) -> None:
    r.decision = decision
    r.decision_reason = (reason or '').strip()[:4000] or None
    r.decided_by = access.author(scope)
    r.decided_at = datetime.now(UTC)


async def _close_item(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    task: ews_models.Task,
    project: ews_models.Project,
) -> None:
    """Move the request item to a cancelled / rejected stage of its workflow (else a done one); best effort: the
    request status stays the requester's truth."""
    from . import _item_update as item_update
    from . import _workflow_service as wfs

    stages = (
        (await wfs.load_stages(session, [task.workflow_id])).get(task.workflow_id) or []
        if task.workflow_id
        else []
    )
    target = next(
        (s for s in stages if s.stage_type in ('rejected', 'cancelled')), None
    ) or next((s for s in stages if items.is_done_type(s.stage_type)), None)
    if target is None or target.id == task.stage_id:
        return
    try:
        async with session.begin_nested():
            await item_update.update_item(
                session, scope, task, project, {'stage_id': str(target.id)}
            )
    except ClientException as error:
        log.info('request item %s not moved: %s', task.id, error.detail)


async def _emit_triaged(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    data: dict[str, Any],
) -> None:
    await events.emit(
        session,
        scope,
        'ppm.request.triaged',
        'task',
        loaded.task.id,
        project_id=loaded.task.project_id,
        data=data,
    )


async def accept(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    data: dict[str, Any],
) -> None:
    """Ppm-1132…1134: ``{mode: item, project_id, item_type?, stage_id?, owner?}`` · ``{mode: in_place, item_type?,
    stage_id?}`` · ``{mode: project, name?, workflow_template_id?, project_template_id?, start_date?, due_date?,
    add_requester?}``."""
    r, t = loaded.request, loaded.task
    _require_open(r)
    mode = data.get('mode')
    if mode not in ACCEPT_MODES:
        raise _error(f'mode must be one of {", ".join(ACCEPT_MODES)}', 'invalid_mode')
    from . import _item_update as item_update

    if mode == 'in_place':
        patch = {
            k: v
            for k, v in (
                ('work_item_type', data.get('item_type')),
                ('stage_id', data.get('stage_id')),
            )
            if v
        }
        if patch:
            await item_update.update_item(session, scope, t, loaded.project, patch)
        _decide(r, scope, 'accepted_in_place')
        r.result_task_id = t.id
    elif mode == 'item':
        target = await access.load_project(
            session, scope, data.get('project_id'), access.TASK, 'create'
        )
        version = await intake.version_of(session, r.form_id, r.form_version)
        mapped = forms.mapped(version.definition if version else {}, r.answers or {})
        result = await items.create_item(
            session,
            scope,
            target,
            items.NewItem(
                name=str(data.get('name') or t.name),
                description=t.description,
                work_item_type=data.get('item_type') or None,
                stage_id=data.get('stage_id') or None,
                owner=data.get('owner') or t.user_id,
                requested_user_id=r.requester_ref,
                labels=mapped.get('labels'),
                priority=t.priority,
                start_date=t.start_date,
                due_date=t.due_date,
                estimated_minutes=t.estimated_minutes,
                cause='intake',
            ),
        )
        await _link(session, scope, loaded.project, t, result, 'relates')
        _decide(r, scope, 'accepted_item')
        r.result_task_id = result.id
    else:
        project = await _accept_project(session, scope, loaded, data)
        _decide(r, scope, 'accepted_project')
        r.result_project_id = project.id
    await session.flush()
    await _emit_triaged(
        session,
        scope,
        loaded,
        {
            'decision': 'accepted',
            'mode': mode,
            'result_task_id': str(r.result_task_id) if r.result_task_id else None,
            'result_project_id': str(r.result_project_id)
            if r.result_project_id
            else None,
        },
    )
    await mirror(session, scope, r)
    if r.status in OPEN:  # nothing mirrored (e.g. same band): accepted
        await set_status(session, scope, r, 'accepted')


async def _accept_project(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    data: dict[str, Any],
) -> ews_models.Project:
    from . import _members as members
    from . import _projects as projects
    from . import _templates as templates

    await access.require_create_project(scope)
    t = loaded.task
    name = str(data.get('name') or t.name).strip()[:200] or t.name
    start = _date(data.get('start_date')) or (
        t.start_date.date() if t.start_date else None
    )
    due = _date(data.get('due_date')) or (t.due_date.date() if t.due_date else None)
    if data.get('project_template_id'):
        template = await access.load_project(
            session, scope, data['project_template_id']
        )
        project = await templates.instantiate(
            session,
            scope,
            template,
            name=name,
            code=None,
            start_date=start or datetime.now(UTC).date(),
            role_map={},
            include_field_values=True,
            include_members=False,
        )
    else:
        project = await projects.create_project(
            session,
            scope,
            name=name,
            template_id=data.get('workflow_template_id') or None,
            description=t.description,
            start_date=datetime.combine(start, datetime.min.time()) if start else None,
            due_date=datetime.combine(due, datetime.min.time()) if due else None,
            data={'from_request': str(t.id)},
        )
    r = loaded.request
    if data.get('add_requester') and r.is_member and r.requester_ref:
        member = await scope_of(r.requester_ref, r.organization_id)
        if member is not None:
            try:
                async with session.begin_nested():
                    await members.set_member(
                        session, scope, project, str(member.user_id), 'project_viewer'
                    )
            except ClientException as error:
                log.info(
                    'requester not added to project %s: %s', project.id, error.detail
                )
    return project


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise _error('dates must be YYYY-MM-DD', 'invalid_date') from error


async def _link(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    source: ews_models.Task,
    target: ews_models.Task,
    kind: str,
) -> None:
    from . import _schedule as schedule

    try:
        async with session.begin_nested():
            await schedule.create_link(session, scope, project, source, target, kind, 0)
    except ClientException as error:
        log.info(
            'request link %s → %s not created: %s', source.id, target.id, error.detail
        )


async def reject(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    reason: str | None,
) -> None:
    """Ppm-1135: a reason is required; sent to the requester."""
    r = loaded.request
    _require_open(r)
    if not (reason or '').strip():
        raise _error('a reason is required', 'reason_required')
    _decide(r, scope, 'rejected', reason)
    await _emit_triaged(
        session, scope, loaded, {'decision': 'rejected', 'reason': r.decision_reason}
    )
    await set_status(session, scope, r, 'rejected', message=r.decision_reason)
    await _close_item(session, scope, loaded.task, loaded.project)


async def merge(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    original_id: object,
) -> None:
    """Ppm-1136: into the original (a duplicate's original when it was merged itself): ``duplicates`` link, the
    duplicate's answers as an internal note on the original."""
    r = loaded.request
    _require_open(r)
    original = await load(session, scope, original_id, triage=True)
    for _ in range(5):
        if (
            original.request.decision != 'merged'
            or original.request.duplicate_of is None
        ):
            break
        original = await load(
            session, scope, original.request.duplicate_of, triage=True
        )
    if original.task.id == loaded.task.id:
        raise _error('a request cannot be merged into itself', 'invalid_merge')
    _decide(r, scope, 'merged')
    r.duplicate_of = original.task.id
    await _link(
        session, scope, loaded.project, loaded.task, original.task, 'duplicates'
    )
    version = await intake.version_of(session, r.form_id, r.form_version)
    lines = [
        f'{a["label"]}: {a["text"]}'
        for a in _answers_out(version.definition if version else {}, r.answers or {})
    ]
    note = (
        f'Merged {loaded.task.code} ({r.requester_name or r.requester_email or r.requester_ref}):\n'
        + '\n'.join(lines)
    )
    await _add_comment(
        session, scope, original.project, original.task, note, internal=True
    )
    await _emit_triaged(
        session,
        scope,
        loaded,
        {'decision': 'duplicate', 'original_id': str(original.task.id)},
    )
    await set_status(
        session,
        scope,
        r,
        'duplicate',
        message=f'{original.task.code} {original.task.name}',
    )
    await _close_item(session, scope, loaded.task, loaded.project)


async def request_info(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    question: str | None,
) -> None:
    """Ppm-1137: a requester-visible question; status needs info until the requester answers."""
    r = loaded.request
    _require_open(r)
    text = (question or '').strip()
    if not text:
        raise _error('a question is required', 'question_required')
    await _add_comment(
        session, scope, loaded.project, loaded.task, text, internal=False
    )
    await _emit_triaged(session, scope, loaded, {'decision': 'info_requested'})
    await set_status(session, scope, r, 'needs_info', message=text)


async def _add_comment(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task,
    text: str,
    *,
    internal: bool,
) -> None:
    from . import _comments as comments

    saved = await comments.create(
        session, scope, project, task, text=text[:20_000], html=None
    )
    if not internal:
        saved.comment.privacy = REQUESTER
        await session.flush()


async def reply(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    loaded: Loaded,
    text: str | None,
    visibility: str,
) -> None:
    """A triager's reply (``requester`` or ``internal``) or a member requester's reply."""
    body = (text or '').strip()
    if not body:
        raise _error('a reply needs a text', 'text_required')
    r = loaded.request
    if not loaded.triager:
        if r.status in CLOSED:
            raise _conflict('this request is closed', 'request_closed')
        await _requester_reply(
            session, r, loaded.task, body, author=access.author(scope), scope=scope
        )
        return
    if visibility not in ('requester', 'internal'):
        raise _error('visibility must be requester or internal', 'invalid_visibility')
    await _add_comment(
        session,
        scope,
        loaded.project,
        loaded.task,
        body,
        internal=visibility == 'internal',
    )
    await events.emit(
        session,
        scope,
        'ppm.request.replied',
        'task',
        loaded.task.id,
        project_id=loaded.task.project_id,
        data={'visibility': visibility, 'author_kind': 'team'},
    )
    if visibility == REQUESTER:
        await _notify_requester(session, r, loaded.task, 'reply', body)


async def _requester_reply(
    session: DBAsyncScopedSession,
    r: PpmRequest,
    task: ews_models.Task,
    body: str,
    *,
    author: str,
    scope: RequestScope | None,
) -> None:
    """A requester's message (member or external): requester-visible, back to review when info was asked, triagers
    and the assignee notified."""
    comment = Comment(
        user_id=author[:320],
        comment_text=body[:20_000],
        content_type='text',
        project_id=str(task.project_id),
        object_id=str(task.id),
        object_type='task',
        tenant_id=r.tenant_id,
        privacy=REQUESTER,
    )
    session.add(comment)
    await session.flush()
    actor = events.Actor(
        'user' if r.is_member else REQUESTER,
        r.requester_ref or r.requester_email,
        r.requester_name,
    )
    await events.emit(
        session,
        scope,
        'ppm.request.replied',
        'task',
        task.id,
        project_id=task.project_id,
        tenant_id=r.tenant_id,
        organization_id=r.organization_id,
        actor=actor,
        data={
            'visibility': REQUESTER,
            'author_kind': 'requester',
            'excerpt': body[:200],
        },
    )
    if r.status == 'needs_info':
        await set_status(session, scope, r, 'in_review')
    form = await session.get(PpmForm, r.form_id)
    slug = await _org_slug(session, r.organization_id)
    await notify(
        session,
        tenant_id=r.tenant_id,
        organization_id=r.organization_id,
        kind='ppm:request_reply',
        recipients=list(
            dict.fromkeys([*([task.user_id] if task.user_id else []), *_triagers(form)])
        ),
        title=f'Requester replied: {task.code} {task.name}'.strip(),
        body=body[:2000],
        link=request_link(slug, task.id),
        subject_type='task',
        subject_id=str(task.id),
        project_id=task.project_id,
        actor_ref=r.requester_ref or r.requester_email,
        actor_name=r.requester_name,
        occurrence=f'reply:{comment.id}',
    )


async def withdraw(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    r: PpmRequest,
    task: ews_models.Task,
) -> None:
    """Before a decision only (409 ``already_decided``)."""
    _require_open(r)
    r.decision = 'withdrawn'
    r.decided_by = r.requester_ref or r.requester_email
    r.decided_at = datetime.now(UTC)
    await events.emit(
        session,
        scope,
        'ppm.request.withdrawn',
        'task',
        task.id,
        project_id=task.project_id,
        tenant_id=r.tenant_id,
        organization_id=r.organization_id,
        actor=events.Actor(
            'user' if r.is_member else REQUESTER,
            r.requester_ref or r.requester_email,
            r.requester_name,
        ),
    )
    await set_status(session, scope, r, 'withdrawn')
    form = await session.get(PpmForm, r.form_id)
    owner = (
        await scope_of(form.owner, r.organization_id, form.owner_user_id)
        if form is not None
        else None
    )
    project = await session.get(ews_models.Project, task.project_id)
    if owner is not None and project is not None:
        await _close_item(session, owner, task, project)


# --- public ------------------------------------------------------------------------------------------------------


async def public_form(session: DBAsyncScopedSession, public_id: str) -> PpmForm:
    form = await session.scalar(
        select(PpmForm).where(
            PpmForm.public_id == str(public_id)[:40],
            PpmForm.deleted_at.is_(None),
            PpmForm.audience == 'public',
        )
    )
    if form is None:
        raise NotFoundException(detail='form not found')
    return form


async def public_form_out(
    session: DBAsyncScopedSession, form: PpmForm
) -> dict[str, Any]:
    organization = await session.get(Organization, form.organization_id)
    out: dict[str, Any] = {
        'name': form.name,
        'description': form.description,
        'status': form.status if form.current_version else 'closed',
        'organization': {'name': organization.name if organization else ''},
        'confirmation': (form.settings or {}).get('confirmation'),
        'redirect_url': (form.settings or {}).get('redirect_url'),
    }
    latest = await intake.latest_version(session, form)
    if form.status == 'published' and latest is not None:
        out |= {
            'version': latest.version,
            'definition': intake.public_definition(latest.definition),
        }
    return out


async def by_token(
    session: DBAsyncScopedSession, token: str
) -> tuple[PpmRequest, ews_models.Task]:
    """The request of a tracking token, valid until 180 days after closing (404 otherwise)."""
    found = (
        await session.execute(
            select(PpmRequest, Task)
            .join(Task, Task.id == PpmRequest.task_id)
            .where(
                PpmRequest.tracking_hash == token_hash(str(token)[:200]),
                Task.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise NotFoundException(detail='request not found')
    r, t = found
    if r.closed_at and r.closed_at < datetime.now(UTC) - timedelta(days=TRACKING_DAYS):
        raise NotFoundException(detail='request not found')
    return r, t


async def tracking_out(
    session: DBAsyncScopedSession, r: PpmRequest, t: ews_models.Task
) -> dict[str, Any]:
    """Ppm-1173 / Ppm-1174: status, timeline, requester-visible replies — no internal data."""
    form = await session.get(PpmForm, r.form_id)
    organization = await session.get(Organization, r.organization_id)
    return {
        'code': t.code,
        'title': t.name,
        'form_name': form.name if form else '',
        'organization': {'name': organization.name if organization else ''},
        'status': r.status,
        'submitted_at': r.submitted_at,
        'decision_reason': r.decision_reason if r.status == 'rejected' else None,
        'timeline': await timeline(session, t.id),
        'conversation': await conversation(session, r, internal=False),
        'can_withdraw': r.status in OPEN,
        'can_reply': r.status not in CLOSED,
    }


async def public_reply(
    session: DBAsyncScopedSession, r: PpmRequest, t: ews_models.Task, text: str | None
) -> None:
    body = (text or '').strip()
    if not body:
        raise _error('a reply needs a text', 'text_required')
    if r.status in CLOSED:
        raise _conflict('this request is closed', 'request_closed')
    recent = await session.scalar(
        select(func.count()).where(
            Comment.object_type == 'task',
            Comment.object_id == str(t.id),
            Comment.privacy == REQUESTER,
            Comment.id >= _uuid7_floor(datetime.now(UTC) - timedelta(minutes=1)),
        )
    )
    if (recent or 0) >= PER_IP_MINUTE:
        raise TooManyRequestsException(
            detail='too many replies, try again later',
            extra={'code': 'rate_limited', 'retry_after': 60},
        )
    await _requester_reply(
        session, r, t, body[:10_000], author=r.requester_email or 'external', scope=None
    )


def _uuid7_floor(at: datetime) -> UUID:
    """The smallest UUIDv7 of an instant (comments have no timestamp column: their id is time-ordered)."""
    return UUID(int=(int(at.timestamp() * 1000) << 80) | (7 << 76) | (2 << 62))
