"""``/api/v1/projects/{project_id}/members`` — project members and roles (Ppm-06xx), generic ``ews.access``
routes (same contract as drives, spaces, blogs, so the web reuses ``@taas/access-ui``)."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, put, status

from ews.access import (
    CandidateOut,
    MemberOut,
    MemberUpsert,
    RoleOut,
    member_candidates,
    object_roles,
)
from ews.security import current_scope

from .. import _access as access
from .. import _members


class ProjectMembersController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Project members',)

    @get(
        '/{project_id}/members',
        summary='Members (direct roles) + inherited organization / tenant admins',
    )
    @db_context_session
    async def list_members(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[MemberOut]:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT_MEMBER, 'read'
        )
        return await _members.members(session, scope, project)

    @get(
        '/{project_id}/member-candidates',
        summary="Members of the project's organization that can be added",
    )
    @db_context_session
    async def member_candidates(
        self, project_id: str, session: DBAsyncScopedSession, q: str | None = None
    ) -> list[CandidateOut]:
        scope = await current_scope()
        await access.load_project(
            session, scope, project_id, access.PROJECT_MEMBER, 'create'
        )
        return await member_candidates(session, scope, q)

    @put(
        '/{project_id}/members',
        summary='Grant or change the role of a user on the project',
    )
    @db_context_session(auto_commit=True)
    async def upsert_member(
        self, project_id: str, data: MemberUpsert, session: DBAsyncScopedSession
    ) -> MemberOut:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT_MEMBER, 'create'
        )
        return await _members.set_member(
            session, scope, project, data.user_id, data.role
        )

    @delete('/{project_id}/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_member(
        self, project_id: str, user_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT_MEMBER, 'delete'
        )
        await _members.drop_member(session, scope, project, user_id)


class PpmRolesController(BaseController):
    api_prefix = '/api/v1/ppm'
    tags = ('Project members',)

    @get('/roles', summary='Roles that can be granted on a project (highest first)')
    async def roles(self) -> list[RoleOut]:
        await current_scope()
        return object_roles(access.PROJECTS)
