"""``/api/v1/knowledge/spaces`` — space directory, settings, members (``ews.access``) and the page tree."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.access import (
    CandidateOut,
    MemberOut,
    MemberUpsert,
    list_members,
    member_candidates,
    remove_member,
    upsert_member,
)
from ews.security import authorize, current_scope

from .. import _pages, _spaces
from .._access import KB_SPACES, PAGE, SPACE, SPACE_MEMBER, load_space
from ..schemas import KbPageCreate, KbPageOut, KbSpaceCreate, KbSpaceOut, KbSpaceUpdate


class KnowledgeSpacesController(BaseController):
    api_prefix = '/api/v1/knowledge'
    tags = ('Knowledge Center',)

    @get(
        '/spaces',
        summary='Space directory: every space of the tenant the caller can read',
    )
    @db_context_session
    async def list_spaces(self, session: DBAsyncScopedSession) -> list[KbSpaceOut]:
        return await _spaces.list_spaces(session, await current_scope())

    @post(
        '/spaces',
        status_code=status.HTTP_201_CREATED,
        summary='Create a space (org admin / kb_admin; Kb-0101)',
    )
    @db_context_session(auto_commit=True)
    async def create_space(
        self, data: KbSpaceCreate, session: DBAsyncScopedSession
    ) -> KbSpaceOut:
        scope = await current_scope()
        await authorize(scope, SPACE, 'create')
        return await _spaces.space_detail(
            session, await _spaces.create_space(session, scope, data)
        )

    @get('/spaces/{space_id}')
    @db_context_session
    async def get_space(
        self, space_id: str, session: DBAsyncScopedSession
    ) -> KbSpaceOut:
        scope = await current_scope()
        return await _spaces.space_detail(
            session, await load_space(session, scope, space_id)
        )

    @patch(
        '/spaces/{space_id}', summary='Name, slug, description, icon, color, visibility'
    )
    @db_context_session(auto_commit=True)
    async def update_space(
        self, space_id: str, data: KbSpaceUpdate, session: DBAsyncScopedSession
    ) -> KbSpaceOut:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, SPACE, 'update')
        await _spaces.update_space(session, scope, access, data)
        return await _spaces.space_detail(
            session, await load_space(session, scope, space_id)
        )

    @delete(
        '/spaces/{space_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete a space (soft)',
    )
    @db_context_session(auto_commit=True)
    async def delete_space(self, space_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await _spaces.delete_space(
            session, scope, await load_space(session, scope, space_id, SPACE, 'delete')
        )

    # --- members (generic ``ews.access`` routes, scoped to the space's organization) ----------------

    @get(
        '/spaces/{space_id}/members',
        summary='Members (direct roles) + inherited organization / tenant admins',
    )
    @db_context_session
    async def list_members(
        self, space_id: str, session: DBAsyncScopedSession
    ) -> list[MemberOut]:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, SPACE_MEMBER, 'read')
        return await list_members(
            session, access.member_scope(scope), KB_SPACES, access.space.id
        )

    @get(
        '/spaces/{space_id}/member-candidates',
        summary="Members of the space's organization that can be added",
    )
    @db_context_session
    async def member_candidates(
        self, space_id: str, session: DBAsyncScopedSession, q: str | None = None
    ) -> list[CandidateOut]:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, SPACE_MEMBER, 'manage')
        return await member_candidates(session, access.member_scope(scope), q)

    @put(
        '/spaces/{space_id}/members',
        summary='Grant or change the role of a user on the space',
    )
    @db_context_session(auto_commit=True)
    async def upsert_member(
        self, space_id: str, data: MemberUpsert, session: DBAsyncScopedSession
    ) -> MemberOut:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, SPACE_MEMBER, 'manage')
        return await upsert_member(
            session,
            access.member_scope(scope),
            KB_SPACES,
            access.space.id,
            data.user_id,
            data.role,
        )

    @delete(
        '/spaces/{space_id}/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def remove_member(
        self, space_id: str, user_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, SPACE_MEMBER, 'manage')
        await remove_member(
            session, access.member_scope(scope), KB_SPACES, access.space.id, user_id
        )

    # --- page tree --------------------------------------------------------------------------------

    @get(
        '/spaces/{space_id}/pages',
        summary='Page tree (flat, parents first; readers: published pages only)',
    )
    @db_context_session
    async def list_pages(
        self, space_id: str, session: DBAsyncScopedSession
    ) -> list[KbPageOut]:
        scope = await current_scope()
        return await _pages.tree(
            session, scope, await load_space(session, scope, space_id, PAGE, 'read')
        )

    @post(
        '/spaces/{space_id}/pages',
        status_code=status.HTTP_201_CREATED,
        summary='Create a page (blank, template or document)',
    )
    @db_context_session(auto_commit=True)
    async def create_page(
        self, space_id: str, data: KbPageCreate, session: DBAsyncScopedSession
    ) -> KbPageOut:
        scope = await current_scope()
        access = await load_space(session, scope, space_id, PAGE, 'create')
        page = await _pages.create_page(session, scope, access, data)
        return _pages.page_out(page, scope, editor=True, names={})
