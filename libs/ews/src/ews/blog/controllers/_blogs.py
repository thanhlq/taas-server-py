"""``/api/v1/blog`` — app gate, roles, blogs of the request's organization, members, document validation."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.access import (
    CandidateOut,
    MemberOut,
    MemberUpsert,
    RoleOut,
    list_members,
    member_candidates,
    object_roles,
    remove_member,
    upsert_member,
)
from ews.security import authorize, current_scope
from ews.sites._document import validate_document

from .. import _access as access
from .. import _service as svc
from .._access import BLOG, BLOG_RES, MEMBER_RES
from ..schemas import (
    BlogAccessOut,
    BlogCreate,
    BlogOut,
    BlogUpdate,
    DocumentIn,
    ValidationOut,
)


class BlogController(BaseController):
    api_prefix = '/api/v1/blog'
    tags = ('Blog',)

    @get('/access', summary='Can the caller open the Blog app (and create blogs)?')
    @db_context_session
    async def access(self, session: DBAsyncScopedSession) -> BlogAccessOut:
        scope = await current_scope()
        allowed, can_create = await access.can_open_app(session, scope)
        return BlogAccessOut(
            allowed=allowed,
            can_create=can_create,
            organization_slug=scope.organization.slug,
        )

    @get('/roles', summary='Roles that can be granted on a blog (highest first)')
    async def list_roles(self) -> list[RoleOut]:
        await current_scope()
        return object_roles(BLOG)

    @post(
        '/validate',
        summary='Validate a post body (site document) without saving — Markdown mode, imports',
    )
    async def validate(self, data: DocumentIn) -> ValidationOut:
        await current_scope()
        issues = [str(i) for i in validate_document(data.doc)]
        return ValidationOut(valid=not issues, issues=issues)

    @get('/blogs', summary='Blogs of the organization the caller can read')
    @db_context_session
    async def list_blogs(self, session: DBAsyncScopedSession) -> list[BlogOut]:
        scope = await current_scope()
        return await svc.list_blogs(session, scope)

    @post(
        '/blogs',
        status_code=status.HTTP_201_CREATED,
        summary='Create a blog (the creator becomes Blog Admin)',
    )
    @db_context_session(auto_commit=True)
    async def create_blog(
        self, data: BlogCreate, session: DBAsyncScopedSession
    ) -> BlogOut:
        scope = await current_scope()
        await authorize(scope, BLOG_RES, 'create')
        blog = await svc.create_blog(session, scope, data)
        return await svc.blog_detail(session, scope, blog)

    @get('/blogs/{blog_id}')
    @db_context_session
    async def get_blog(self, blog_id: str, session: DBAsyncScopedSession) -> BlogOut:
        scope = await current_scope()
        return await svc.blog_detail(
            session, scope, await access.load_blog(session, scope, blog_id)
        )

    @patch(
        '/blogs/{blog_id}',
        summary='Name, slug, description, locale, settings, status (archive / restore)',
    )
    @db_context_session(auto_commit=True)
    async def update_blog(
        self, blog_id: str, data: BlogUpdate, session: DBAsyncScopedSession
    ) -> BlogOut:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, BLOG_RES, 'update')
        return await svc.blog_detail(
            session, scope, await svc.update_blog(session, scope, blog, data)
        )

    @delete(
        '/blogs/{blog_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete a blog (soft)',
    )
    @db_context_session(auto_commit=True)
    async def delete_blog(self, blog_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        await svc.delete_blog(
            session,
            scope,
            await access.load_blog(session, scope, blog_id, BLOG_RES, 'delete'),
        )

    # --- members ----------------------------------------------------------------------------------

    @get(
        '/blogs/{blog_id}/members',
        summary='Members (roles on the blog) + inherited organization admins',
    )
    @db_context_session
    async def list_members(
        self, blog_id: str, session: DBAsyncScopedSession
    ) -> list[MemberOut]:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, MEMBER_RES, 'read')
        return await list_members(session, scope, BLOG, blog.id)

    @get(
        '/blogs/{blog_id}/member-candidates',
        summary='Organization members that can be added',
    )
    @db_context_session
    async def member_candidates(
        self, blog_id: str, session: DBAsyncScopedSession, q: str | None = None
    ) -> list[CandidateOut]:
        scope = await current_scope()
        await access.load_blog(session, scope, blog_id, MEMBER_RES, 'manage')
        return await member_candidates(session, scope, q)

    @put(
        '/blogs/{blog_id}/members',
        summary='Grant or change the role of a user on the blog',
    )
    @db_context_session(auto_commit=True)
    async def upsert_member(
        self, blog_id: str, data: MemberUpsert, session: DBAsyncScopedSession
    ) -> MemberOut:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, MEMBER_RES, 'manage')
        return await upsert_member(
            session, scope, BLOG, blog.id, data.user_id, data.role
        )

    @delete(
        '/blogs/{blog_id}/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def remove_member(
        self, blog_id: str, user_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, MEMBER_RES, 'manage')
        await remove_member(session, scope, BLOG, blog.id, user_id)
