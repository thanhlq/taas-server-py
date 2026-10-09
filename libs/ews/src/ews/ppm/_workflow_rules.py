"""Transition rules and team workflows (taas-specs/ppm/project/project-workflow §"Transition rules & team workflows",
Ppm-0201…0206).

A stage may restrict the next stages of its items (``allowed_next_stages``: stage ids of the same workflow, empty =
any), require an owner or a due date to enter it, and give items without an owner its default assignee
(``auto_assign`` + ``default_assignee_ids[0]``). Moves to another workflow and *reopen* are free; *complete* picks the
first done-band stage the current stage allows. A workflow with privacy ``team`` is visible to the members of its
organization team (``team_id``), its assigned users and the project's responsible user.
"""

from __future__ import annotations

from typing import Any

import db.models.ews as ews_models
from db.models.core import Team, TeamMember
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import ConflictException, parse_uuid

Stage = ews_models.WorkflowStage
REQUIREMENTS = ('assignee', 'due_date')


# --- stage rules ----------------------------------------------------------------------------------


def allowed_next(stage: Stage | None) -> list[str]:
    """Stage ids an item of ``stage`` may move to (empty = any)."""
    raw = stage.allowed_next_stages if stage is not None else None
    if isinstance(raw, dict):
        raw = raw.get('ids')
    return [str(x) for x in raw] if isinstance(raw, list) else []


def default_assignee(stage: Stage) -> str | None:
    raw = stage.default_assignee_ids
    if isinstance(raw, dict):
        raw = raw.get('ids')
    if stage.auto_assign and isinstance(raw, list) and raw:
        return str(raw[0])
    return None


def rules_out(stage: Stage) -> dict[str, Any]:
    raw = stage.default_assignee_ids
    ids = raw.get('ids') if isinstance(raw, dict) else raw
    return {
        'allowed_next_stage_ids': allowed_next(stage),
        'require_assignee': bool(stage.require_assignee),
        'require_due_date': bool(stage.require_due_date),
        'auto_assign': bool(stage.auto_assign),
        'default_assignee_id': str(ids[0]) if isinstance(ids, list) and ids else None,
    }


def apply_rules(
    stage: Stage, data: dict[str, Any], siblings: list[Stage], clear: set[str]
) -> None:
    """Set the rule fields of a stage from a create / update request (unknown next stages → 400)."""
    if 'allowed_next_stage_ids' in data and data['allowed_next_stage_ids'] is not None:
        ids = {str(s.id) for s in siblings}
        wanted = [str(x) for x in data['allowed_next_stage_ids']]
        unknown = [x for x in wanted if x not in ids or x == str(stage.id)]
        if unknown:
            raise ClientException(
                detail='allowed next stages must be other stages of the same workflow'
            )
        stage.allowed_next_stages = list(dict.fromkeys(wanted)) or None
    for key in ('require_assignee', 'require_due_date', 'auto_assign'):
        if data.get(key) is not None:
            setattr(stage, key, bool(data[key]))
    if data.get('default_assignee_id'):
        stage.default_assignee_ids = [str(data['default_assignee_id']).strip()]
    if 'allowed_next_stage_ids' in clear:
        stage.allowed_next_stages = None
    if 'default_assignee_id' in clear:
        stage.default_assignee_ids = None
        stage.auto_assign = False


def check_transition(old: Stage | None, new: Stage) -> None:
    """409 ``transition_not_allowed`` when ``old`` restricts its next stages and ``new`` is not one of them."""
    if old is None or old.id == new.id or old.workflow_id != new.workflow_id:
        return
    allowed = allowed_next(old)
    if allowed and str(new.id) not in allowed:
        raise ConflictException(
            detail=f'an item cannot move from "{old.name}" to "{new.name}"',
            extra={
                'code': 'transition_not_allowed',
                'from_stage_id': str(old.id),
                'to_stage_id': str(new.id),
                'allowed': allowed,
            },
        )


def missing_requirements(task: ews_models.Task, stage: Stage) -> list[str]:
    missing: list[str] = []
    if stage.require_assignee and not task.user_id:
        missing.append('assignee')
    if stage.require_due_date and not task.due_date:
        missing.append('due_date')
    return missing


def check_requirements(task: ews_models.Task, stage: Stage) -> None:
    missing = missing_requirements(task, stage)
    if missing:
        raise ConflictException(
            detail=f'"{stage.name}" needs: {", ".join(missing)}',
            extra={
                'code': 'stage_requirements',
                'stage_id': str(stage.id),
                'missing': missing,
            },
        )


def first_allowed(current: Stage | None, candidates: list[Stage]) -> Stage | None:
    """The first of ``candidates`` reachable from ``current`` (all are when it has no restriction)."""
    allowed = allowed_next(current)
    if not allowed:
        return candidates[0] if candidates else None
    return next((c for c in candidates if str(c.id) in allowed), None)


# --- teams ----------------------------------------------------------------------------------------


async def viewer_teams(session: DBAsyncScopedSession, scope: RequestScope) -> set[str]:
    """Team ids of the caller (team workflows they see / land on)."""
    rows = await session.scalars(
        select(TeamMember.team_id).where(TeamMember.user_id == scope.user_id)
    )
    return {str(t) for t in rows.all()}


async def organization_teams(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[dict[str, Any]]:
    """Teams of the request's organization with their size and whether the caller is a member."""
    mine = await viewer_teams(session, scope)
    counts = (
        select(TeamMember.team_id, func.count().label('n'))
        .group_by(TeamMember.team_id)
        .subquery()
    )
    rows = await session.execute(
        select(Team.id, Team.name, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.team_id == Team.id)
        .where(Team.organization_id == scope.organization_id)
        .order_by(Team.name)
    )
    return [
        {
            'id': str(i),
            'name': name,
            'member_count': int(n),
            'is_member': str(i) in mine,
        }
        for i, name, n in rows.all()
    ]


async def check_team(
    session: DBAsyncScopedSession, project: ews_models.Project, team_id: object
) -> str:
    """A team of the project's organization (400 otherwise); returns its id."""
    tid = parse_uuid(team_id, 'team')
    found = await session.scalar(
        select(Team.id).where(
            Team.id == tid, Team.organization_id == project.organization_id
        )
    )
    if found is None:
        raise ClientException(detail='the team is not in this organization')
    return str(tid)


__all__ = [
    'REQUIREMENTS',
    'allowed_next',
    'apply_rules',
    'check_requirements',
    'check_team',
    'check_transition',
    'default_assignee',
    'first_allowed',
    'missing_requirements',
    'organization_teams',
    'rules_out',
    'viewer_teams',
]
