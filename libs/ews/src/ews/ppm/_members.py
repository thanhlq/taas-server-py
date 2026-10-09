"""Project members and roles (Ppm-06xx, app-roles-spec §5): the generic ``ews.access`` members operations on
``project:<id>`` plus the PPM rules — a project keeps at least one Project Admin (409 ``last_admin``), a personal
project (Inbox) has no other member (409 ``personal_project``) — and the member events."""

from __future__ import annotations

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession

from ews.access import MemberOut, list_members, remove_member, upsert_member
from ews.authz import ProjectRoles, grants_in
from ews.security import RequestScope
from ews.shared import ConflictException

from . import _events as events
from ._access import PROJECTS

ADMIN = ProjectRoles.PROJECT_ADMIN.value


def _not_personal(project: ews_models.Project) -> None:
    if project.kind == 'personal':
        raise ConflictException(
            detail='an Inbox has no other members: move the item to a team project to share it',
            extra={'code': 'personal_project'},
        )


async def _admins(project_id: object) -> set[str]:
    return {
        u for u, r, _ in await grants_in([PROJECTS.domain(project_id)]) if r == ADMIN
    }


async def members(
    session: DBAsyncScopedSession, scope: RequestScope, project: ews_models.Project
) -> list[MemberOut]:
    return await list_members(session, scope, PROJECTS, project.id)


async def set_member(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    user_id: str,
    role: str,
) -> MemberOut:
    _not_personal(project)
    PROJECTS.require_role(role)
    previous = await PROJECTS.role_of(user_id, project.id)
    if previous == ADMIN and role != ADMIN and await _admins(project.id) <= {user_id}:
        raise ConflictException(
            detail='a project needs at least one Project Admin',
            extra={'code': 'last_admin'},
        )
    out = await upsert_member(session, scope, PROJECTS, project.id, user_id, role)
    if previous != role:
        await events.emit(
            session,
            scope,
            'ppm.project.member_added'
            if previous is None
            else 'ppm.project.member_role_changed',
            'project',
            project.id,
            project_id=project.id,
            changes={'role': {'from': previous, 'to': role}},
            data={
                'user_id': out.user_id,
                'email': out.email,
                'name': out.name,
                'project': project.name,
            },
        )
    return out


async def drop_member(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    user_id: str,
) -> None:
    previous = await PROJECTS.role_of(user_id, project.id)
    if previous == ADMIN and await _admins(project.id) <= {user_id}:
        raise ConflictException(
            detail='a project needs at least one Project Admin',
            extra={'code': 'last_admin'},
        )
    await remove_member(session, scope, PROJECTS, project.id, user_id)
    await events.emit(
        session,
        scope,
        'ppm.project.member_removed',
        'project',
        project.id,
        project_id=project.id,
        changes={'role': {'from': previous, 'to': None}},
        data={'user_id': user_id, 'project': project.name},
    )


async def readers(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    project: ews_models.Project,
) -> set[str] | None:
    """Lower-case ids and e-mails of the users who can read the project (members + inherited admins); ``None`` =
    everybody (development sign-in, or no request scope)."""
    if scope is None or scope.is_dev:
        return None
    out: set[str] = set()
    for m in await members(session, scope, project):
        out.add(m.user_id.lower())
        if m.email:
            out.add(m.email.lower())
    return out
