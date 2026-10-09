"""Generic approvals (taas-specs/ppm/work-model/work-model-spec.md Ppm-0865…0873, §5.4).

One approval object for every subject type; a subject type registers how it loads (title, project, snapshot) and
what an outcome does (:func:`register_subject`). Steps run in order; each has approvers resolved to users at request
time and frozen (users, a project role, the item owner) and a rule ``any`` / ``all``. Decisions: approve · reject ·
request changes; history in ``taas_ppm_approval_events`` (append-only, Ppm-0871).

Built-in subject: ``task`` — any item can ask for approval; a pending approval blocks its completion, and an item of
behaviour ``approval`` is done only through its approval (approved → done stage; rejected → rejected / cancelled).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import (
    PpmApproval,
    PpmApprovalApprover,
    PpmApprovalEvent,
    PpmApprovalPolicy,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import or_, select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, parse_uuid

from . import _events as events
from . import _work_items as items

APPROVAL = EwsResources.APPROVAL.value
DECISIONS = ('approved', 'rejected', 'changes_requested')
APPROVER_TYPES = ('user', 'project_role', 'item_owner')
NO_SELF_APPROVAL = frozenset({'timesheet', 'expense_report', 'budget'})


def _now() -> datetime:
    return datetime.now(UTC)


def me_refs(scope: RequestScope) -> set[str]:
    return {r.lower() for r in (str(scope.user_id), scope.email or '') if r}


def me(scope: RequestScope) -> str:
    return (scope.email or str(scope.user_id)).lower()


# --- subject types -----------------------------------------------------------------------------------


@dataclass(slots=True)
class Subject:
    title: str
    project: ews_models.Project | None
    snapshot: dict[str, Any]
    record: Any = None
    owner: str | None = None


Loader = Callable[
    [DBAsyncScopedSession, RequestScope | None, str, str], Awaitable[Subject]
]
"""``(session, scope, subject_id, action)`` → the subject, after checking ``action`` on it (``read`` · ``request``)."""
Outcome = Callable[
    [DBAsyncScopedSession, RequestScope | None, PpmApproval, Subject], Awaitable[None]
]


@dataclass(slots=True)
class SubjectType:
    key: str
    load: Loader
    on_outcome: Outcome | None = None
    allow_self_approval: bool = True


_SUBJECTS: dict[str, SubjectType] = {}


def register_subject(subject: SubjectType) -> SubjectType:
    _SUBJECTS[subject.key] = subject
    return subject


def subject_type(key: str) -> SubjectType:
    found = _SUBJECTS.get(key)
    if found is None:
        raise ClientException(detail=f'unknown approval subject {key!r}')
    return found


def subject_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]


# --- steps -------------------------------------------------------------------------------------------


@dataclass(slots=True)
class StepIn:
    name: str | None = None
    rule: str = 'any'
    approvers: list[dict[str, str]] = field(default_factory=list)
    """``[{type: user | project_role | item_owner, ref}]``."""


def add_working_days(start: datetime, days: int) -> datetime:
    """``start`` + ``days`` working days (Monday–Friday; the organization calendar comes with resources, V3)."""
    out, left = start, max(0, days)
    while left:
        out += timedelta(days=1)
        if out.weekday() < 5:
            left -= 1
    return out


async def _resolve(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    subject: Subject,
    approver: dict[str, str],
) -> list[tuple[str, str]]:
    """``[(user ref, resolved_from)]`` of one approver spec."""
    kind = approver.get('type') or 'user'
    ref = (approver.get('ref') or '').strip()
    if kind == 'user':
        return [(ref.lower(), 'user')] if ref else []
    if kind == 'item_owner':
        return [(subject.owner.lower(), 'item_owner')] if subject.owner else []
    if kind == 'project_role':
        if subject.project is None or scope is None:
            return []
        from ._members import members

        out = []
        for m in await members(session, scope, subject.project):
            if m.role == ref and not getattr(m, 'inherited', False):
                out.append(((m.email or m.user_id).lower(), f'project_role:{ref}'))
        return out
    raise ClientException(detail=f'unknown approver type {kind!r}')


async def _fallback(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    subject: Subject,
    requester: str,
) -> list[tuple[str, str]]:
    """Empty step → the project's admins (then nobody: 400)."""
    if subject.project is None or scope is None:
        return []
    from ._members import members

    return [
        ((m.email or m.user_id).lower(), 'fallback:project_admin')
        for m in await members(session, scope, subject.project)
        if m.role == 'project_admin' and (m.email or m.user_id).lower() != requester
    ]


async def _policy_steps(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    subject_key: str,
    subject: Subject,
) -> tuple[PpmApprovalPolicy | None, list[StepIn]]:
    """First matching policy (project ones first, then organization) for the subject type."""
    p = PpmApprovalPolicy
    project_id = subject.project.id if subject.project is not None else None
    rows = await session.scalars(
        select(p)
        .where(
            p.organization_id == scope.organization_id,
            p.subject_type == subject_key,
            p.archived_at.is_(None),
            or_(p.project_id.is_(None), p.project_id == project_id),
        )
        .order_by(p.project_id.nulls_last(), p.position)
    )
    for policy in rows.all():
        cond = policy.conditions or {}
        types = cond.get('item_types') or []
        if types and subject.snapshot.get('item_type') not in types:
            continue
        minimum = cond.get('min_amount')
        if minimum is not None:
            amount = subject.snapshot.get('amount')
            if amount is None or float(amount) < float(minimum):
                continue
        return policy, [
            StepIn(
                name=s.get('name'),
                rule=s.get('rule') or 'any',
                approvers=list(s.get('approvers') or []),
            )
            for s in policy.steps or []
        ]
    return None, []


# --- request ------------------------------------------------------------------------------------------


async def _record(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    approval: PpmApproval,
    action: str,
    *,
    step: int | None = None,
    comment: str | None = None,
) -> None:
    session.add(
        PpmApprovalEvent(
            tenant_id=approval.tenant_id,
            approval_id=approval.id,
            action=action,
            actor_ref=me(scope) if scope else 'system',
            step=step,
            round=approval.round,
            comment=comment,
            subject_hash=subject_hash(approval.subject_snapshot or {}),
        )
    )
    await session.flush()


async def approvers_of(
    session: DBAsyncScopedSession, approval_id: UUID
) -> list[PpmApprovalApprover]:
    a = PpmApprovalApprover
    return list(
        (
            await session.scalars(
                select(a)
                .where(a.approval_id == approval_id)
                .order_by(a.step, a.created_at)
            )
        ).all()
    )


async def _emit(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    approval: PpmApproval,
    topic: str,
    data: dict[str, Any] | None = None,
) -> None:
    await events.emit(
        session,
        scope,
        topic,
        'approval',
        approval.id,
        project_id=approval.project_id,
        tenant_id=approval.tenant_id,
        organization_id=approval.organization_id,
        data={
            'subject_type': approval.subject_type,
            'subject_id': approval.subject_id,
            'title': approval.title,
            'round': approval.round,
            'step': approval.current_step,
            'requested_by': approval.requested_by,
            **(data or {}),
        },
    )


async def _pending_step_refs(
    session: DBAsyncScopedSession, approval: PpmApproval
) -> list[str]:
    return [
        a.user_ref
        for a in await approvers_of(session, approval.id)
        if a.step == approval.current_step and a.decision == 'pending'
    ]


async def request(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    subject_key: str,
    subject_id: str,
    steps: list[StepIn] | None = None,
    policy_id: Any = None,
    due_at: datetime | None = None,
    note: str | None = None,
    subject_part: str | None = None,
) -> PpmApproval:
    """Ask for approval (Ppm-0865, Ppm-0866): steps given, from ``policy_id`` or the first matching policy."""
    kind = subject_type(subject_key)
    subject = await kind.load(session, scope, subject_id, 'request')
    project_id = subject.project.id if subject.project is not None else None
    a = PpmApproval
    pending = await session.scalar(
        select(a.id).where(
            a.subject_type == subject_key,
            a.subject_id == subject_id,
            a.status == 'pending',
            a.subject_part.is_(None)
            if subject_part is None
            else a.subject_part == subject_part,
        )
    )
    if pending:
        raise ConflictException(
            detail='an approval is already pending', extra={'code': 'approval_pending'}
        )
    policy: PpmApprovalPolicy | None = None
    if policy_id:
        policy = await session.get(
            PpmApprovalPolicy, parse_uuid(policy_id, 'approval policy')
        )
        if (
            policy is None
            or policy.organization_id != scope.organization_id
            or policy.archived_at
        ):
            raise NotFoundException(detail='approval policy not found')
        steps = [
            StepIn(
                name=s.get('name'),
                rule=s.get('rule') or 'any',
                approvers=list(s.get('approvers') or []),
            )
            for s in policy.steps
        ]
    elif not steps:
        policy, steps = await _policy_steps(session, scope, subject_key, subject)
    requester = me(scope)
    self_ok = (
        kind.allow_self_approval
        and subject_key not in NO_SELF_APPROVAL
        and (policy.allow_self_approval if policy else False)
    )
    approval = PpmApproval(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        project_id=project_id,
        subject_type=subject_key,
        subject_id=subject_id,
        subject_part=subject_part,
        title=subject.title[:300],
        note=(note or None),
        subject_snapshot=subject.snapshot,
        policy_id=policy.id if policy else None,
        requested_by=requester,
        due_at=due_at
        or (
            add_working_days(_now(), policy.due_working_days)
            if policy and policy.due_working_days
            else None
        ),
        status='pending',
        round=1,
        current_step=1,
    )
    session.add(approval)
    await session.flush()
    rows: list[PpmApprovalApprover] = []
    for n, step in enumerate(steps or [], start=1):
        if step.rule not in ('any', 'all'):
            raise ClientException(detail=f'unknown step rule {step.rule!r}')
        resolved: list[tuple[str, str]] = []
        for spec in step.approvers:
            resolved += await _resolve(session, scope, subject, spec)
        resolved = list(dict.fromkeys(resolved))
        if not self_ok:
            resolved = [r for r in resolved if r[0] not in me_refs(scope)]
        if not resolved:
            resolved = await _fallback(session, scope, subject, requester)
        if not resolved:
            raise ClientException(
                detail=f'step {n} has no approver',
                extra={'code': 'no_approver', 'step': n},
            )
        for ref, source in resolved:
            rows.append(
                PpmApprovalApprover(
                    tenant_id=scope.tenant_id,
                    approval_id=approval.id,
                    step=n,
                    step_name=(step.name or None),
                    step_rule=step.rule,
                    user_ref=ref,
                    resolved_from=source,
                )
            )
    session.add_all(rows)
    await session.flush()
    await _record(session, scope, approval, 'requested', comment=note)
    if not rows:  # no step: approved on request (actor system, audited)
        approval.status = 'approved'
        approval.decided_at = _now()
        await _record(session, None, approval, 'approved')
        await _emit(session, scope, approval, 'ppm.approval.approved')
        await _outcome(session, scope, approval, subject)
        return approval
    await _emit(
        session,
        scope,
        approval,
        'ppm.approval.requested',
        {'approvers': await _pending_step_refs(session, approval)},
    )
    return approval


# --- decisions ----------------------------------------------------------------------------------------


async def _outcome(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    approval: PpmApproval,
    subject: Subject | None = None,
) -> None:
    kind = _SUBJECTS.get(approval.subject_type)
    if kind is None or kind.on_outcome is None:
        return
    subject = subject or await kind.load(session, None, approval.subject_id, 'system')
    await kind.on_outcome(session, scope, approval, subject)


async def _advance(
    session: DBAsyncScopedSession, scope: RequestScope | None, approval: PpmApproval
) -> None:
    """Move past every finished step; approve when none is left."""
    rows = await approvers_of(session, approval.id)
    steps = sorted({r.step for r in rows})
    for n in steps:
        if n < approval.current_step:
            continue
        step_rows = [r for r in rows if r.step == n]
        rule = step_rows[0].step_rule
        approved = [r for r in step_rows if r.decision == 'approved']
        pending = [r for r in step_rows if r.decision == 'pending']
        done = (
            (rule == 'any' and approved)
            or (rule == 'all' and not pending and approved)
            or not (approved or pending)
        )
        if not done:
            if approval.current_step != n:
                approval.current_step = n
                await _emit(
                    session,
                    scope,
                    approval,
                    'ppm.approval.step_started',
                    {'approvers': [r.user_ref for r in pending]},
                )
                await _emit(
                    session,
                    scope,
                    approval,
                    'ppm.approval.requested',
                    {'approvers': [r.user_ref for r in pending]},
                )
            await session.flush()
            return
        for r in pending:  # step done by "any": the others are skipped
            r.decision = 'skipped'
    approval.status = 'approved'
    approval.decided_at = _now()
    await session.flush()
    await _record(session, scope, approval, 'approved')
    await _emit(session, scope, approval, 'ppm.approval.approved')
    await _outcome(session, scope, approval)


async def decide(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    approval: PpmApproval,
    decision: str,
    comment: str | None = None,
) -> PpmApproval:
    """Approve · reject · request changes (comment required for the last two) — §5.4."""
    if decision not in DECISIONS:
        raise ClientException(detail=f'unknown decision {decision!r}')
    comment = (comment or '').strip() or None
    if decision != 'approved' and not comment:
        raise ClientException(
            detail='a comment is required', extra={'code': 'comment_required'}
        )
    if approval.status != 'pending':
        raise ConflictException(
            detail='this approval is closed',
            extra={'code': 'approval_closed', 'status': approval.status},
        )
    mine = [
        r
        for r in await approvers_of(session, approval.id)
        if r.user_ref in me_refs(scope)
    ]
    if not mine:
        raise PermissionDeniedException(
            detail='you are not an approver', extra={'code': 'not_approver'}
        )
    current = [r for r in mine if r.step == approval.current_step]
    if not current:
        raise ConflictException(
            detail='your step is not the current one',
            extra={'code': 'not_current_step'},
        )
    row = current[0]
    if row.decision == decision:
        return approval  # idempotent
    if row.decision != 'pending':
        raise ConflictException(
            detail='you already decided', extra={'code': 'already_decided'}
        )
    row.decision, row.decided_at, row.comment = decision, _now(), comment
    await _record(session, scope, approval, decision, step=row.step, comment=comment)
    await _emit(
        session,
        scope,
        approval,
        'ppm.approval.step_decided',
        {'decision': decision, 'step': row.step},
    )
    if decision == 'approved':
        await _advance(session, scope, approval)
        return approval
    for other in await approvers_of(session, approval.id):
        if other.decision == 'pending':
            other.decision = 'skipped'
    approval.status = decision
    approval.decided_at = _now()
    await session.flush()
    await _emit(
        session, scope, approval, f'ppm.approval.{decision}', {'comment': comment}
    )
    await _outcome(session, scope, approval)
    return approval


async def delegate(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    approval: PpmApproval,
    user_ref: str,
    comment: str | None,
) -> PpmApproval:
    if approval.status != 'pending':
        raise ConflictException(
            detail='this approval is closed', extra={'code': 'approval_closed'}
        )
    target = (user_ref or '').strip().lower()
    if not target or target in me_refs(scope):
        raise ClientException(detail='delegate to someone else')
    row = next(
        (
            r
            for r in await approvers_of(session, approval.id)
            if r.user_ref in me_refs(scope)
            and r.step == approval.current_step
            and r.decision == 'pending'
        ),
        None,
    )
    if row is None:
        raise PermissionDeniedException(
            detail='you have no pending decision here', extra={'code': 'not_approver'}
        )
    row.delegated_from, row.user_ref = row.user_ref, target
    await session.flush()
    await _record(session, scope, approval, 'delegated', step=row.step, comment=comment)
    await _emit(
        session,
        scope,
        approval,
        'ppm.approval.delegated',
        {'to': target, 'approvers': [target]},
    )
    await _emit(
        session, scope, approval, 'ppm.approval.requested', {'approvers': [target]}
    )
    return approval


async def can_manage(scope: RequestScope, approval: PpmApproval) -> bool:
    if approval.project_id is not None:
        from ._access import PROJECTS

        return await PROJECTS.allowed(scope, approval.project_id, APPROVAL, 'manage')
    return await is_allowed(scope, APPROVAL, 'manage', scope.org_domains())


async def cancel(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    approval: PpmApproval,
    comment: str | None = None,
) -> PpmApproval:
    if approval.status != 'pending':
        raise ConflictException(
            detail='this approval is closed', extra={'code': 'approval_closed'}
        )
    if approval.requested_by not in me_refs(scope) and not await can_manage(
        scope, approval
    ):
        raise PermissionDeniedException(detail='only the requester can cancel')
    for r in await approvers_of(session, approval.id):
        if r.decision == 'pending':
            r.decision = 'skipped'
    approval.status = 'cancelled'
    approval.decided_at = _now()
    await session.flush()
    await _record(session, scope, approval, 'cancelled', comment=comment)
    await _emit(session, scope, approval, 'ppm.approval.cancelled')
    return approval


async def resubmit(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    approval: PpmApproval,
    comment: str | None = None,
) -> PpmApproval:
    """After changes were requested (or a rejection): a new round, every step pending again, a fresh snapshot."""
    if approval.status not in ('changes_requested', 'rejected', 'outdated'):
        raise ConflictException(
            detail='nothing to resubmit', extra={'code': 'not_resubmittable'}
        )
    if approval.requested_by not in me_refs(scope):
        raise PermissionDeniedException(detail='only the requester can resubmit')
    subject = await subject_type(approval.subject_type).load(
        session, scope, approval.subject_id, 'request'
    )
    approval.subject_snapshot = subject.snapshot
    approval.round += 1
    approval.current_step = 1
    approval.status = 'pending'
    approval.decided_at = None
    for r in await approvers_of(session, approval.id):
        r.decision, r.decided_at, r.comment = 'pending', None, None
    await session.flush()
    await _record(session, scope, approval, 'resubmitted', comment=comment)
    await _emit(
        session,
        scope,
        approval,
        'ppm.approval.requested',
        {'approvers': await _pending_step_refs(session, approval)},
    )
    return approval


# --- reads ----------------------------------------------------------------------------------------------


async def get(
    session: DBAsyncScopedSession, scope: RequestScope, approval_id: Any
) -> PpmApproval:
    """An approval the caller may read: named approver, requester, or reader of the subject (Ppm-0873)."""
    row = await session.get(PpmApproval, parse_uuid(approval_id, 'approval'))
    if row is None or row.organization_id != scope.organization_id:
        raise NotFoundException(detail='approval not found')
    mine = me_refs(scope)
    if row.requested_by in mine or any(
        r.user_ref in mine or (r.delegated_from or '') in mine
        for r in await approvers_of(session, row.id)
    ):
        return row
    await subject_type(row.subject_type).load(session, scope, row.subject_id, 'read')
    return row


async def history(
    session: DBAsyncScopedSession, approval_id: UUID
) -> list[PpmApprovalEvent]:
    e = PpmApprovalEvent
    return list(
        (
            await session.scalars(
                select(e)
                .where(e.approval_id == approval_id)
                .order_by(e.occurred_at, e.id)
            )
        ).all()
    )


async def waiting_for(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[tuple[PpmApproval, PpmApprovalApprover]]:
    """Approvals whose current step waits for the caller (My Work, Ppm-0873)."""
    a, r = PpmApproval, PpmApprovalApprover
    rows = await session.execute(
        select(a, r)
        .join(r, r.approval_id == a.id)
        .where(
            a.organization_id == scope.organization_id,
            a.status == 'pending',
            r.step == a.current_step,
            r.decision == 'pending',
            r.user_ref.in_(list(me_refs(scope))),
        )
        .order_by(a.due_at.nulls_last(), a.requested_at)
    )
    return [(x, y) for x, y in rows.all()]


async def for_subject(
    session: DBAsyncScopedSession, subject_key: str, subject_id: str
) -> list[PpmApproval]:
    a = PpmApproval
    return list(
        (
            await session.scalars(
                select(a)
                .where(a.subject_type == subject_key, a.subject_id == subject_id)
                .order_by(a.requested_at.desc())
            )
        ).all()
    )


# --- policies ---------------------------------------------------------------------------------------------


def _clean_steps(steps: Any) -> list[dict[str, Any]]:
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        rule = s.get('rule') or 'any'
        if rule not in ('any', 'all'):
            raise ClientException(detail=f'unknown step rule {rule!r}')
        approvers = []
        for ap in s.get('approvers') or []:
            kind = (ap or {}).get('type') or 'user'
            if kind not in APPROVER_TYPES:
                raise ClientException(detail=f'unknown approver type {kind!r}')
            approvers.append(
                {'type': kind, 'ref': str((ap or {}).get('ref') or '').strip()}
            )
        out.append(
            {'name': (s.get('name') or None), 'rule': rule, 'approvers': approvers}
        )
    return out


async def require_manage_policies(scope: RequestScope, project_id: UUID | None) -> None:
    if project_id is None:
        ok = await is_allowed(scope, APPROVAL, 'manage', scope.org_domains())
    else:
        from ._access import PROJECTS

        ok = await PROJECTS.allowed(scope, project_id, APPROVAL, 'manage')
    if not ok:
        raise PermissionDeniedException(detail=f'missing permission {APPROVAL}:manage')


async def save_policy(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    data: dict[str, Any],
    row: PpmApprovalPolicy | None = None,
) -> PpmApprovalPolicy:
    project_id = (
        row.project_id
        if row
        else (
            parse_uuid(data['project_id'], 'project')
            if data.get('project_id')
            else None
        )
    )
    await require_manage_policies(scope, project_id)
    if row is None:
        name = (data.get('name') or '').strip()
        if not name:
            raise ClientException(detail='a policy needs a name')
        row = PpmApprovalPolicy(
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            project_id=project_id,
            name=name[:200],
            subject_type=data.get('subject_type') or 'task',
        )
        session.add(row)
    elif 'name' in data:
        row.name = (data['name'] or row.name).strip()[:200]
    if 'conditions' in data:
        row.conditions = {
            k: v
            for k, v in (data['conditions'] or {}).items()
            if k in ('item_types', 'min_amount', 'currency', 'categories')
        }
    if 'steps' in data:
        row.steps = _clean_steps(data['steps'])
    if 'due_working_days' in data:
        row.due_working_days = data['due_working_days']
    if 'allow_self_approval' in data:
        row.allow_self_approval = bool(data['allow_self_approval'])
    if data.get('archived') is not None:
        row.archived_at = _now() if data['archived'] else None
    await session.flush()
    return row


# --- the task subject -------------------------------------------------------------------------------------


async def _load_task(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    subject_id: str,
    action: str,
) -> Subject:
    from ._access import TASK, load_task

    if scope is None or action == 'system':
        task = await session.get(ews_models.Task, parse_uuid(subject_id, 'task'))
        if task is None:
            raise NotFoundException(detail='task not found')
        project = (
            await session.get(ews_models.Project, task.project_id)
            if task.project_id
            else None
        )
    else:
        task, project = await load_task(session, scope, subject_id, TASK, 'read')
        if action == 'request':
            from ._access import PROJECTS

            if not await PROJECTS.allowed(scope, project.id, APPROVAL, 'request'):
                raise PermissionDeniedException(
                    detail=f'missing permission {APPROVAL}:request'
                )
    return Subject(
        title=f'{task.code or ""} {task.name or ""}'.strip(),
        project=project,
        record=task,
        owner=task.user_id,
        snapshot={
            'name': task.name,
            'code': task.code,
            'item_type': task.work_item_type,
            'due_date': task.due_date.date().isoformat() if task.due_date else None,
            'estimated_minutes': task.estimated_minutes,
            'progress': task.progress,
        },
    )


async def _task_outcome(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    approval: PpmApproval,
    subject: Subject,
) -> None:
    """Items of behaviour ``approval`` follow their approval (§5.1)."""
    task: ews_models.Task = subject.record
    project = subject.project
    if task is None or project is None or task.behaviour != 'approval':
        return
    if approval.status == 'approved':
        await items.complete(session, scope, task, project, cascade=True)  # type: ignore[arg-type]
    elif approval.status == 'rejected' and task.workflow_id:
        from . import _workflow_service as wfs

        stages = (await wfs.load_stages(session, [task.workflow_id])).get(
            task.workflow_id
        ) or []
        target = next((s for s in stages if s.stage_type == 'rejected'), None) or next(
            (s for s in stages if s.stage_type == 'cancelled'), None
        )
        if target is not None:
            before = items.state(task)
            task.stage_id, task.stage_type = target.id, target.stage_type
            await session.flush()
            await items.refresh_rollups(session, task.parent_id)
            await items.record_update(session, scope, task, project, before)


register_subject(SubjectType('task', _load_task, _task_outcome))


@items.register_done_guard
async def _approval_guard(
    session: DBAsyncScopedSession, task: ews_models.Task
) -> items.DoneBlock | None:
    """A pending approval blocks completion (Ppm-0868); an ``approval`` item is done only through its approval."""
    approvals = await for_subject(session, 'task', str(task.id))
    if any(a.status == 'pending' for a in approvals):
        return items.DoneBlock(
            'approval_pending', 'an approval is pending on this item', {}
        )
    if task.behaviour == 'approval' and not any(
        a.status == 'approved' for a in approvals
    ):
        return items.DoneBlock(
            'approval_required', 'this item is done through its approval', {}
        )
    return None
