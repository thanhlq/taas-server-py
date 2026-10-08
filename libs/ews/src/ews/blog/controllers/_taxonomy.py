"""``/api/v1/blog/blogs/{blog_id}/…`` — categories, tags and author profiles (Blog-0104): read with
``blog.taxonomy:read``, change with ``blog.taxonomy:manage``."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status

from ews.security import current_scope

from .. import _access as access
from .. import _taxonomy as svc
from .._access import TAXONOMY_RES
from ..schemas import (
    BlogAuthorCreate,
    BlogAuthorOut,
    BlogAuthorUpdate,
    BlogCategoryCreate,
    BlogCategoryOut,
    BlogCategoryUpdate,
    BlogTagCreate,
    BlogTagOut,
    BlogTagUpdate,
)


class BlogTaxonomyController(BaseController):
    api_prefix = '/api/v1/blog/blogs/{blog_id}'
    tags = ('Blog',)

    # --- categories -------------------------------------------------------------------------------

    @get('/categories', summary='Categories (ordered) with their post counts')
    @db_context_session
    async def list_categories(
        self, blog_id: str, session: DBAsyncScopedSession
    ) -> list[BlogCategoryOut]:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, TAXONOMY_RES, 'read')
        return await svc.list_categories(session, blog)

    @post('/categories', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_category(
        self, blog_id: str, data: BlogCategoryCreate, session: DBAsyncScopedSession
    ) -> BlogCategoryOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.create_category(session, scope, blog, data)

    @patch(
        '/categories/{category_id}',
        summary='Name, slug, description, SEO, position (reorder)',
    )
    @db_context_session(auto_commit=True)
    async def update_category(
        self,
        blog_id: str,
        category_id: str,
        data: BlogCategoryUpdate,
        session: DBAsyncScopedSession,
    ) -> BlogCategoryOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.update_category(session, blog, category_id, data)

    @delete(
        '/categories/{category_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete (posts keep no category)',
    )
    @db_context_session(auto_commit=True)
    async def delete_category(
        self, blog_id: str, category_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        await svc.delete_category(session, blog, category_id)

    # --- tags -------------------------------------------------------------------------------------

    @get('/tags', summary='Tags (by name, optional search) with their post counts')
    @db_context_session
    async def list_tags(
        self, blog_id: str, session: DBAsyncScopedSession, q: str | None = None
    ) -> list[BlogTagOut]:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, TAXONOMY_RES, 'read')
        return await svc.list_tags(session, blog, q)

    @post('/tags', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_tag(
        self, blog_id: str, data: BlogTagCreate, session: DBAsyncScopedSession
    ) -> BlogTagOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.create_tag(session, blog, data)

    @patch('/tags/{tag_id}')
    @db_context_session(auto_commit=True)
    async def update_tag(
        self,
        blog_id: str,
        tag_id: str,
        data: BlogTagUpdate,
        session: DBAsyncScopedSession,
    ) -> BlogTagOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.update_tag(session, blog, tag_id, data)

    @delete(
        '/tags/{tag_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete (removed from its posts)',
    )
    @db_context_session(auto_commit=True)
    async def delete_tag(
        self, blog_id: str, tag_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        await svc.delete_tag(session, blog, tag_id)

    # --- authors ----------------------------------------------------------------------------------

    @get(
        '/authors',
        summary='Author profiles (users and guest authors) with their post counts',
    )
    @db_context_session
    async def list_authors(
        self, blog_id: str, session: DBAsyncScopedSession
    ) -> list[BlogAuthorOut]:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, TAXONOMY_RES, 'read')
        return await svc.list_authors(session, blog)

    @post(
        '/authors',
        status_code=status.HTTP_201_CREATED,
        summary='Create an author profile (user_id optional)',
    )
    @db_context_session(auto_commit=True)
    async def create_author(
        self, blog_id: str, data: BlogAuthorCreate, session: DBAsyncScopedSession
    ) -> BlogAuthorOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.create_author(session, scope, blog, data)

    @patch('/authors/{author_id}')
    @db_context_session(auto_commit=True)
    async def update_author(
        self,
        blog_id: str,
        author_id: str,
        data: BlogAuthorUpdate,
        session: DBAsyncScopedSession,
    ) -> BlogAuthorOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        return await svc.update_author(session, scope, blog, author_id, data)

    @delete(
        '/authors/{author_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete (409 while credited on posts)',
    )
    @db_context_session(auto_commit=True)
    async def delete_author(
        self, blog_id: str, author_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, TAXONOMY_RES, 'manage', writable=True
        )
        await svc.delete_author(session, blog, author_id)
