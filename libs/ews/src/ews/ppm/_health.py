"""Project health (taas-specs/ppm/health/project-health-spec.md, ADR-44): policies (organization + project exception),
the facts the rules read, recompute → today's snapshot (``ppm.project.health_changed`` when a rating changes),
overrides, history and the refresh job. Rules: ``_health_engine`` (pure).

Recompute = on read when today's snapshot is missing or older than the project's last event / policy change, on
demand, and by the job ``ppm.health_refresh`` (every 60 s: projects changed more than 60 s ago, the first run of a day,
expired overrides, 2-year retention). Dates are UTC days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import (
    PpmAuditEvent,
    PpmHealthOverride,
    PpmHealthPolicy,
    PpmHealthSnapshot,
    PpmSettings,
    PpmWorkItemLink,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from ews.authz import EwsResources
from ews.notifications import Kind, notify, register_job, register_kinds
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException

from . import _access as access
from . import _events as events
from . import _health_engine as engine
from . import _settings
from . import _work_items as items
from .controllers._task_support import uuid7_time

HEALTH = EwsResources.HEALTH.value
HEALTH_POLICY = EwsResources.HEALTH_POLICY.value
Project = ews_models.Project
Task = ews_models.Task

CLOSED = ('Completed', 'Cancelled', 'Archived', 'Template')
"""Statuses the job does not recompute: their last snapshot stays (§5.10)."""
DIMENSION_CAPABILITIES: dict[str, tuple[str, ...]] = {
    'budget': ('budgets',),
    'risk': ('dependencies', 'raid'),
}
"""A dimension is ⚪ *not tracked* when none of its capabilities is on (Ppm-1608)."""
RETENTION_DAYS = 730
DEBOUNCE = timedelta(seconds=60)
BATCH = 200
OWN_EVENTS = ('ppm.project.health%', 'ppm.health_policy.%')
"""Events of this module: they never make a snapshot stale."""

register_kinds(Kind('ppm:health_changed', 'ppm', email='instant'))


def today() -> date:
    return datetime.now(UTC).date()


def _now() -> datetime:
    return datetime.now(UTC)


def _error(detail: str, code: str, **extra: Any) -> ClientException:
    return ClientException(detail=detail, extra={'code': code, **extra})


# --- policies -------------------------------------------------------------------------------------


@dataclass(slots=True)
class Policy:
    thresholds: dict[str, dict[str, Any]]
    """Effective: defaults ← organization ← project exception."""
    dimensions: frozenset[str]
    version: int
    """Organization version + project exception version (both only grow)."""
    source: str
    """``default`` · ``organization`` · ``project``."""
    updated_at: datetime | None
    organization: PpmHealthPolicy | None
    project: PpmHealthPolicy | None


async def _policy_row(
    session: DBAsyncScopedSession, organization_id: UUID, project_id: UUID | None
) -> PpmHealthPolicy | None:
    p = PpmHealthPolicy
    cond = p.project_id == project_id if project_id else p.project_id.is_(None)
    return await session.scalar(
        select(p).where(p.organization_id == organization_id, cond)
    )


async def policy_for(
    session: DBAsyncScopedSession, organization_id: UUID, project_id: UUID | None = None
) -> Policy:
    org = await _policy_row(session, organization_id, None)
    own = (
        await _policy_row(session, organization_id, project_id) if project_id else None
    )
    dims = (
        own.dimensions
        if own is not None and own.dimensions is not None
        else org.dimensions
        if org is not None
        else None
    )
    stamps = [r.updated_at for r in (org, own) if r is not None and r.updated_at]
    return Policy(
        thresholds=engine.thresholds(
            org.thresholds if org else None, own.thresholds if own else None
        ),
        dimensions=frozenset(engine.DIMENSIONS if dims is None else dims),
        version=(org.version if org else 0) + (own.version if own else 0),
        source='project' if own else 'organization' if org else 'default',
        updated_at=max(stamps) if stamps else None,
        organization=org,
        project=own,
    )


async def can_update_policy(scope: RequestScope) -> bool:
    return await is_allowed(scope, HEALTH_POLICY, 'update', scope.org_domains())


async def update_policy(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    version: int,
    thresholds: dict[str, Any] | None,
    dimensions: list[str] | None,
    project: ews_models.Project | None = None,
) -> None:
    """Change the organization policy or a project exception (``version`` must match: 409 ``stale_policy``).
    An organization change makes today's snapshots of its projects stale; a project exception recomputes now."""
    org_id = scope.organization_id
    row = await _policy_row(session, org_id, project.id if project else None)
    if (row.version if row else 0) != version:
        raise ConflictException(
            detail='the health policy changed meanwhile', extra={'code': 'stale_policy'}
        )
    try:
        patch = engine.clean_thresholds(thresholds or {})
    except ValueError as exc:
        raise _error(str(exc), 'invalid_policy') from exc
    if dimensions is not None and not set(dimensions) <= set(engine.DIMENSIONS):
        raise _error(
            f'dimensions must be among {", ".join(engine.DIMENSIONS)}', 'invalid_policy'
        )
    if row is None:
        row = PpmHealthPolicy(
            tenant_id=scope.tenant_id,
            organization_id=org_id,
            project_id=project.id if project else None,
            version=0,
        )
        session.add(row)
    before = {'thresholds': row.thresholds, 'dimensions': row.dimensions}
    row.thresholds = engine.merge_thresholds(row.thresholds, patch)
    if dimensions is not None:
        row.dimensions = (
            None
            if set(dimensions) == set(engine.DIMENSIONS)
            else sorted(set(dimensions))
        )
    org = None if project is None else await _policy_row(session, org_id, None)
    try:
        engine.check_order(
            engine.thresholds(org.thresholds if org else None, row.thresholds)
            if project
            else engine.thresholds(row.thresholds)
        )
    except ValueError as exc:
        raise _error(str(exc), 'invalid_policy') from exc
    row.version = (row.version or 0) + 1
    row.updated_at = _now()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.health_policy.updated',
        'health_policy',
        row.id,
        project_id=project.id if project else None,
        changes=events.diff(
            before, {'thresholds': row.thresholds, 'dimensions': row.dimensions}
        ),
    )
    if project is not None:
        await compute(session, project)
    else:
        await _forget_today(session, org_id)


async def reset_policy(
    session: DBAsyncScopedSession, scope: RequestScope, project: ews_models.Project
) -> None:
    """Drop a project exception: back to the organization policy."""
    row = await _policy_row(session, scope.organization_id, project.id)
    if row is None:
        return
    await session.delete(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.health_policy.reset',
        'health_policy',
        row.id,
        project_id=project.id,
    )
    await compute(session, project)


STALE = -1
"""``policy_version`` of a snapshot to recompute (its policy changed); the row stays the comparison base."""


async def _forget_today(session: DBAsyncScopedSession, organization_id: UUID) -> None:
    """Today's snapshots of an organization are recomputed on the next read / job run (policy changed)."""
    await session.execute(
        update(PpmHealthSnapshot)
        .where(
            PpmHealthSnapshot.organization_id == organization_id,
            PpmHealthSnapshot.snapshot_date == today(),
        )
        .values(policy_version=STALE)
    )


async def _capabilities(
    session: DBAsyncScopedSession, organization_id: UUID
) -> dict[str, bool]:
    row = await session.scalar(
        select(PpmSettings).where(PpmSettings.organization_id == organization_id)
    )
    return _settings.capabilities_of(row)


def enabled_dimensions(policy: Policy, capabilities: dict[str, bool]) -> frozenset[str]:
    """The policy's dimensions whose capabilities are on (budget ← ``budgets``; risk ← ``dependencies`` or ``raid``)."""
    return frozenset(
        d
        for d in policy.dimensions
        if d not in DIMENSION_CAPABILITIES
        or any(capabilities.get(c, False) for c in DIMENSION_CAPABILITIES[d])
    )


# --- facts ----------------------------------------------------------------------------------------


def _ref(t: ews_models.Task) -> engine.Ref:
    return engine.Ref(str(t.id), t.code, t.name or '')


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


async def _reference(
    session: DBAsyncScopedSession, project: ews_models.Project, day: date
) -> tuple[int, date] | None:
    """Items of the first snapshot on or after the start date (scope reference, C1)."""
    s = PpmHealthSnapshot
    q = select(s.snapshot_date, s.metrics).where(
        s.project_id == project.id, s.snapshot_date < day
    )
    start = _day(project.start_date)
    if start:
        q = q.where(s.snapshot_date >= start)
    row = (await session.execute(q.order_by(s.snapshot_date).limit(1))).first()
    if (
        row
        and isinstance(row.metrics, dict)
        and isinstance(row.metrics.get('items'), int)
    ):
        return row.metrics['items'], row.snapshot_date
    return None


async def facts(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    t: dict[str, dict[str, Any]],
    capabilities: dict[str, bool],
    day: date,
) -> engine.Facts:
    """What the rules read about ``project`` on ``day`` (items = counted behaviours, cancelled / rejected excluded)."""
    f = engine.Facts(
        today=day, start=_day(project.start_date), due=_day(project.due_date)
    )
    q = t['quality']
    defect_types = set(q['defect_types'])
    soon = day + timedelta(days=t['resources']['unassigned_days'])
    old = datetime.combine(
        day - timedelta(days=q['defect_age_days']), datetime.min.time()
    )
    tasks = list(
        (
            await session.scalars(
                select(Task).where(
                    Task.project_id == project.id, Task.deleted_at.is_(None)
                )
            )
        ).all()
    )
    by_id = {x.id: x for x in tasks}
    open_ids: set[UUID] = set()
    done = 0
    overdue: list[ews_models.Task] = []
    for x in tasks:
        if not items.counts_in_progress(x.stage_type, x.behaviour):
            continue
        f.items += 1
        defect = (x.work_item_type or '').lower() in defect_types
        f.defects_tracked = f.defects_tracked or defect
        if items.is_done(x):
            done += 1
            continue
        open_ids.add(x.id)
        due = _day(x.due_date)
        if x.behaviour == 'milestone':
            if due and due < day:
                f.milestones_late.append(_ref(x))
            continue
        f.open += 1
        if due and due < day:
            overdue.append(x)
        if not x.user_id and due and due <= soon:
            f.unassigned_due_soon.append(_ref(x))
        if defect:
            f.open_defects += 1
            born = uuid7_time(x.id)
            if (
                (x.priority or 0) >= q['critical_priority']
                and born is not None
                and born <= old
            ):
                f.old_critical_defects.append(_ref(x))
    overdue.sort(key=lambda x: x.due_date or datetime.max)
    f.overdue = [_ref(x) for x in overdue]
    f.progress = round(done * 100 / f.items) if f.items else 0
    f.completed = project.status == 'Completed' or (f.items > 0 and f.progress >= 100)

    ref = await _reference(session, project, day)
    if ref is not None:
        f.reference_items, f.reference_date = ref
    elif f.start is None or day >= f.start:
        f.reference_items, f.reference_date = f.items, day

    since = datetime.combine(day - timedelta(days=30), datetime.min.time(), UTC)
    a = PpmAuditEvent
    for event, n in (
        await session.execute(
            select(a.event, func.count(func.distinct(a.subject_id)))
            .where(
                a.project_id == project.id,
                a.event.in_(('ppm.task.completed', 'ppm.task.reopened')),
                a.occurred_at >= since,
            )
            .group_by(a.event)
        )
    ).all():
        if event == 'ppm.task.completed':
            f.done_30d = int(n)
        else:
            f.reopened_30d = int(n)

    if capabilities.get('dependencies'):
        await _dependency_facts(session, project, f, by_id, open_ids, day)
    return f


async def _dependency_facts(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    f: engine.Facts,
    by_id: dict[UUID, ews_models.Task],
    open_ids: set[UUID],
    day: date,
) -> None:
    """K3: incoming FS / SS links into open items whose predecessor is overdue or due after the item's start."""
    link = PpmWorkItemLink
    rows = [
        r
        for r in (
            await session.scalars(
                select(link).where(
                    link.target_project_id == project.id, link.type.in_(('fs', 'ss'))
                )
            )
        ).all()
        if r.target_task_id in open_ids
    ]
    f.links = len(rows)
    missing = {r.source_task_id for r in rows} - by_id.keys()
    if missing:
        for x in (
            await session.scalars(
                select(Task).where(Task.id.in_(missing), Task.deleted_at.is_(None))
            )
        ).all():
            by_id[x.id] = x
    risky: dict[UUID, engine.Ref] = {}
    for r in rows:
        pred, succ = by_id.get(r.source_task_id), by_id[r.target_task_id]
        if pred is None or items.is_done(pred):
            continue
        pred_due, succ_start = _day(pred.due_date), _day(succ.start_date)
        if (pred_due and pred_due < day) or (
            pred_due and succ_start and pred_due > succ_start
        ):
            risky.setdefault(succ.id, _ref(succ))
    f.dependency_risks = list(risky.values())


# --- recompute ------------------------------------------------------------------------------------


def _ratings(row: PpmHealthSnapshot) -> dict[str, str]:
    out = {d: getattr(row, d) for d in engine.DIMENSIONS}
    out['overall'] = row.overall
    out['overall_effective'] = row.overall_effective
    return out


async def _latest(
    session: DBAsyncScopedSession, project_id: UUID, day: date | None = None
) -> PpmHealthSnapshot | None:
    s = PpmHealthSnapshot
    q = select(s).where(s.project_id == project_id)
    if day is not None:
        q = q.where(s.snapshot_date == day)
    return await session.scalar(q.order_by(s.snapshot_date.desc()).limit(1))


async def compute(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    *,
    day: date | None = None,
) -> PpmHealthSnapshot:
    """Evaluate the rules and rewrite today's snapshot (one at a time per project); emit
    ``ppm.project.health_changed`` when a rating changed and tell an override's author when the computed overall moved."""
    day = day or today()
    await session.execute(
        text('select pg_advisory_xact_lock(hashtextextended(:k, 0))'),
        {'k': f'ppm-health:{project.id}'},
    )
    policy = await policy_for(session, project.organization_id, project.id)
    capabilities = await _capabilities(session, project.organization_id)
    f = await facts(session, project, policy.thresholds, capabilities, day)
    health = engine.evaluate(
        f, policy.thresholds, enabled_dimensions(policy, capabilities)
    )
    override = await active_override(session, project, day)
    effective = override.rating if override else health.overall
    previous = await _latest(session, project.id)
    before = _ratings(previous) if previous is not None else None
    ratings = {k: d.rating for k, d in health.dimensions.items()}
    values: dict[str, Any] = {
        **ratings,
        'overall': health.overall,
        'overall_effective': effective,
        'override_id': override.id if override else None,
        'reasons': {k: d.reasons for k, d in health.dimensions.items()},
        'metrics': health.metrics,
        'policy_version': policy.version,
        'computed_at': _now(),
    }
    s = PpmHealthSnapshot
    await session.execute(
        pg_insert(s)
        .values(
            tenant_id=project.tenant_id,
            organization_id=project.organization_id,
            project_id=project.id,
            snapshot_date=day,
            **values,
        )
        .on_conflict_do_update(
            index_elements=[s.project_id, s.snapshot_date],
            set_={**values, 'updated_at': _now()},
        )
    )
    row = await session.scalar(
        select(s)
        .where(s.project_id == project.id, s.snapshot_date == day)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    after = {**ratings, 'overall': health.overall, 'overall_effective': effective}
    changes = engine.changed(before, after)
    if changes:
        await events.emit(
            session,
            None,
            'ppm.project.health_changed',
            'project',
            project.id,
            project_id=project.id,
            tenant_id=project.tenant_id,
            organization_id=project.organization_id,
            changes=changes,
            data={
                'overall': health.overall,
                'overall_effective': effective,
                'reasons': {
                    k: health.dimensions[k].reasons[:1]
                    for k in changes
                    if k in health.dimensions
                },
            },
            actor=events.Actor('system'),
            cause='health',
        )
        if override is not None and 'overall' in changes:
            await notify(
                session,
                tenant_id=project.tenant_id,
                organization_id=project.organization_id,
                kind='ppm:health_changed',
                recipients=[override.set_by],
                title=(
                    f'{project.name}: computed health is now {health.overall} '
                    f'(your manual rating {override.rating} applies until {override.expires_on.isoformat()})'
                ),
                link=f'/ppm/projects/{project.id}/settings?tab=health',
                subject_type='project',
                subject_id=str(project.id),
                project_id=project.id,
                via='automation',
                occurrence=f'health:{project.id}:{day.isoformat()}:{health.overall}',
                data={'overall': health.overall, 'override': override.rating},
            )
    return row


async def _last_event(
    session: DBAsyncScopedSession, project_id: UUID
) -> datetime | None:
    a = PpmAuditEvent
    return await session.scalar(
        select(func.max(a.occurred_at)).where(
            a.project_id == project_id, *(~a.event.like(p) for p in OWN_EVENTS)
        )
    )


async def current(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> PpmHealthSnapshot:
    """Today's snapshot, recomputed first when missing or older than the project's last change / policy change."""
    day = today()
    row = await _latest(session, project.id, day)
    if row is not None:
        policy = await policy_for(session, project.organization_id, project.id)
        last = await _last_event(session, project.id)
        fresh = (
            row.policy_version != STALE
            and (last is None or last <= row.computed_at)
            and (policy.updated_at is None or policy.updated_at <= row.computed_at)
        )
        if fresh:
            return row
    return await compute(session, project, day=day)


async def history(
    session: DBAsyncScopedSession,
    project_id: UUID,
    start: date | None,
    end: date | None,
) -> list[PpmHealthSnapshot]:
    """Daily snapshots between ``start`` and ``end`` (default: the last 90 days; at most 2 years)."""
    end = end or today()
    start = start or end - timedelta(days=89)
    if start > end or (end - start).days > RETENTION_DAYS:
        raise _error(
            f'the period must be between 1 and {RETENTION_DAYS + 1} days',
            'invalid_period',
        )
    s = PpmHealthSnapshot
    return list(
        (
            await session.scalars(
                select(s)
                .where(
                    s.project_id == project_id,
                    s.snapshot_date >= start,
                    s.snapshot_date <= end,
                )
                .order_by(s.snapshot_date)
            )
        ).all()
    )


async def latest_ratings(
    session: DBAsyncScopedSession, project_ids: list[UUID]
) -> dict[UUID, str]:
    """``{project_id: overall_effective}`` of each project's latest snapshot (list and card badges)."""
    if not project_ids:
        return {}
    s = PpmHealthSnapshot
    rows = await session.execute(
        select(s.project_id, s.overall_effective)
        .where(s.project_id.in_(project_ids))
        .distinct(s.project_id)
        .order_by(s.project_id, s.snapshot_date.desc())
    )
    return dict(rows.tuples().all())


# --- overrides ------------------------------------------------------------------------------------


async def active_override(
    session: DBAsyncScopedSession, project: ews_models.Project, day: date | None = None
) -> PpmHealthOverride | None:
    """The project's active override; one past its expiry becomes ``expired`` (+ event) and is not returned."""
    day = day or today()
    o = PpmHealthOverride
    row = await session.scalar(
        select(o).where(o.project_id == project.id, o.status == 'active')
    )
    if row is None or row.expires_on >= day:
        return row
    row.status = 'expired'
    await session.flush()
    await events.emit(
        session,
        None,
        'ppm.project.health_override_expired',
        'project',
        project.id,
        project_id=project.id,
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        data={'rating': row.rating, 'expires_on': row.expires_on},
        actor=events.Actor('system'),
        cause='health',
    )
    return None


async def set_override(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    *,
    rating: str,
    reason: str,
    expires_on: date | None,
) -> PpmHealthSnapshot:
    """Manual overall rating (§5.9): 🟢 / 🟡 / 🔴, reason ≥ 10 characters, expiry today … today + ``max_days``
    (default + ``default_days``); replaces an active one."""
    if rating not in ('green', 'amber', 'red'):
        raise _error('rating must be green, amber or red', 'invalid_rating')
    reason = (reason or '').strip()
    if len(reason) < 10:
        raise _error(
            'a reason of at least 10 characters is required', 'reason_required'
        )
    day = today()
    limits = (
        await policy_for(session, project.organization_id, project.id)
    ).thresholds['override']
    expires_on = expires_on or day + timedelta(days=limits['default_days'])
    if not day <= expires_on <= day + timedelta(days=limits['max_days']):
        raise _error(
            f'the override must expire between today and {limits["max_days"]} days from now',
            'invalid_expiry',
            max_days=limits['max_days'],
        )
    who = access.author(scope)
    current_row = await active_override(session, project, day)
    if current_row is not None:
        current_row.status = 'cleared'
        current_row.cleared_by = who
        current_row.cleared_at = _now()
        await session.flush()
    row = PpmHealthOverride(
        tenant_id=project.tenant_id,
        organization_id=project.organization_id,
        project_id=project.id,
        rating=rating,
        reason=reason,
        expires_on=expires_on,
        set_by=who,
        status='active',
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.project.health_override_set',
        'project',
        project.id,
        project_id=project.id,
        data={'rating': rating, 'expires_on': expires_on},
        reason=reason,
    )
    return await compute(session, project, day=day)


async def clear_override(
    session: DBAsyncScopedSession, scope: RequestScope, project: ews_models.Project
) -> PpmHealthSnapshot:
    row = await active_override(session, project)
    if row is not None:
        row.status = 'cleared'
        row.cleared_by = access.author(scope)
        row.cleared_at = _now()
        await session.flush()
        await events.emit(
            session,
            scope,
            'ppm.project.health_override_cleared',
            'project',
            project.id,
            project_id=project.id,
            data={'rating': row.rating},
        )
    return await compute(session, project)


async def override_of(
    session: DBAsyncScopedSession, row: PpmHealthSnapshot
) -> PpmHealthOverride | None:
    if row.override_id is None:
        return None
    return await session.get(PpmHealthOverride, row.override_id)


# --- job ------------------------------------------------------------------------------------------


async def refresh(
    session: DBAsyncScopedSession,
    now: datetime | None = None,
    *,
    organization_id: UUID | None = None,
) -> int:
    """Job: expire overrides, recompute projects changed > 60 s ago or without today's snapshot (≤ ``BATCH`` per
    run, each in a savepoint), drop snapshots older than 2 years. Organizations with health off are skipped;
    ``organization_id`` limits the run to one organization (tests)."""
    now = now or _now()
    day = now.date()
    o = PpmHealthOverride
    only = [Project.organization_id == organization_id] if organization_id else []
    expired = set(
        (
            await session.scalars(
                select(o.project_id).where(
                    o.status == 'active',
                    o.expires_on < day,
                    *(
                        [o.organization_id == organization_id]
                        if organization_id
                        else []
                    ),
                )
            )
        ).all()
    )
    s = aliased(PpmHealthSnapshot)
    a = PpmAuditEvent
    last = (
        select(func.max(a.occurred_at))
        .where(a.project_id == Project.id, *(~a.event.like(p) for p in OWN_EVENTS))
        .scalar_subquery()
    )
    stale = (
        await session.scalars(
            select(Project.id)
            .outerjoin(s, and_(s.project_id == Project.id, s.snapshot_date == day))
            .where(
                Project.kind == 'project',
                Project.deleted_at.is_(None),
                or_(Project.status.is_(None), Project.status.not_in(CLOSED)),
                *only,
                or_(
                    s.id.is_(None),
                    s.policy_version == STALE,
                    and_(last > s.computed_at, last < now - DEBOUNCE),
                ),
            )
            .order_by(Project.id)
            .limit(BATCH)
        )
    ).all()
    health_on: dict[UUID, bool] = {}
    done = 0
    for project_id in [*expired, *(p for p in stale if p not in expired)]:
        project = await session.get(Project, project_id)
        if project is None or project.organization_id is None:
            continue
        org = project.organization_id
        if org not in health_on:
            health_on[org] = (await _capabilities(session, org)).get('health', False)
        if not health_on[org]:
            continue
        async with session.begin_nested():
            await compute(session, project, day=day)
        done += 1
    await session.execute(
        delete(PpmHealthSnapshot).where(
            PpmHealthSnapshot.snapshot_date < day - timedelta(days=RETENTION_DAYS)
        )
    )
    return done


register_job('ppm.health_refresh', 60, refresh)


# --- wire -----------------------------------------------------------------------------------------


async def permissions(
    scope: RequestScope, project: ews_models.Project
) -> dict[str, bool]:
    domains = access.project_domains(scope, project.id)
    return {
        'can_update': await is_allowed(scope, HEALTH, 'update', domains),
        'can_override': await is_allowed(scope, HEALTH, 'override', domains),
        'can_update_policy': await can_update_policy(scope),
    }


def snapshot_out(
    row: PpmHealthSnapshot,
    project: ews_models.Project,
    override: PpmHealthOverride | None,
) -> dict[str, Any]:
    reasons = row.reasons or {}
    return {
        'project_id': str(row.project_id),
        'snapshot_date': row.snapshot_date,
        'computed_at': row.computed_at,
        'overall': row.overall,
        'overall_effective': row.overall_effective,
        'dimensions': [
            {'key': d, 'rating': getattr(row, d), 'reasons': reasons.get(d) or []}
            for d in engine.DIMENSIONS
        ],
        'metrics': row.metrics or {},
        'policy_version': row.policy_version,
        'override': override_out(override)
        if override is not None and override.status == 'active'
        else None,
        'status_suggestion': engine.status_suggestion(
            project.status, row.overall_effective
        ),
    }


def override_out(o: PpmHealthOverride) -> dict[str, Any]:
    return {
        'id': str(o.id),
        'rating': o.rating,
        'reason': o.reason,
        'expires_on': o.expires_on,
        'set_by': o.set_by,
        'set_at': o.created_at,
        'status': o.status,
    }


def policy_out(policy: Policy, own: PpmHealthPolicy | None) -> dict[str, Any]:
    return {
        'thresholds': policy.thresholds,
        'own': (own.thresholds or {}) if own else {},
        'dimensions': sorted(policy.dimensions, key=engine.DIMENSIONS.index),
        'version': own.version if own else 0,
        'source': policy.source,
        'defaults': engine.DEFAULT_THRESHOLDS,
    }
