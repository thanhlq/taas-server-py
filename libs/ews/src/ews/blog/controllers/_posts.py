"""``/api/v1/blog`` — posts: list (filters + counts), create, metadata, draft autosave, revisions, soft lock."""

from __future__ import annotations

from db.models.blog import Blog, BlogPost, BlogPostRevision
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.security import RequestScope, current_scope
from ews.shared import user_names

from .. import _access as access
from .. import _posts as svc
from .._access import POST_RES
from .._release import blog_url
from ..schemas import (
    BlogDraftOut,
    BlogDraftSave,
    BlogLockOut,
    BlogLockRequest,
    BlogPostCreate,
    BlogPostDetailOut,
    BlogPostListOut,
    BlogPostUpdate,
    BlogRevisionDetailOut,
    BlogRevisionOut,
)


def _draft_out(
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    revision: BlogPostRevision,
    *,
    created: bool,
) -> BlogDraftOut:
    """Draft save / restore answer, with the address after the change (it follows the title while ``slug_auto``)."""
    return BlogDraftOut(
        revision_id=str(revision.id),
        created_at=revision.created_at,
        new_revision=created,
        word_count=post.word_count,
        reading_minutes=post.reading_minutes,
        slug=post.slug,
        slug_auto=post.slug_auto,
        public_url=f'{blog_url(scope.organization.slug, blog.slug)}{post.slug}',
    )


class BlogPostsController(BaseController):
    api_prefix = '/api/v1/blog'
    tags = ('Blog',)

    @get(
        '/blogs/{blog_id}/posts',
        summary='Posts with filters and the counts of the quick tabs',
    )
    @db_context_session
    async def list_posts(
        self,
        blog_id: str,
        session: DBAsyncScopedSession,
        status: str | None = None,
        category_id: str | None = None,
        tag_id: str | None = None,
        author_id: str | None = None,
        q: str | None = None,
        featured: bool | None = None,
        sort: str = 'updated',
        order: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> BlogPostListOut:
        scope = await current_scope()
        blog = await access.load_blog(session, scope, blog_id, POST_RES, 'read')
        return await svc.list_posts(
            session,
            scope,
            blog,
            status=status,
            category_id=category_id,
            tag_id=tag_id,
            author_id=author_id,
            q=q,
            featured=featured,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )

    @post(
        '/blogs/{blog_id}/posts',
        status_code=status.HTTP_201_CREATED,
        summary='Create a draft post',
    )
    @db_context_session(auto_commit=True)
    async def create_post(
        self, blog_id: str, data: BlogPostCreate, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog = await access.load_blog(
            session, scope, blog_id, POST_RES, 'create', writable=True
        )
        post = await svc.create_post(session, scope, blog, data)
        return await svc.post_detail(session, scope, blog, post)

    @get(
        '/posts/{post_id}',
        summary="Post with its draft body and the caller's permissions",
    )
    @db_context_session
    async def get_post(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, post = await access.load_post(session, scope, post_id)
        return await svc.post_detail(session, scope, blog, post)

    @patch(
        '/posts/{post_id}',
        summary='Metadata: title, slug, excerpt, cover, category, tags, authors, SEO',
    )
    @db_context_session(auto_commit=True)
    async def update_post(
        self, post_id: str, data: BlogPostUpdate, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, post = await access.load_post(session, scope, post_id, writable=True)
        await access.require_edit(session, scope, blog, post)
        await svc.update_post(session, scope, blog, post, data)
        return await svc.post_detail(session, scope, blog, post)

    @delete(
        '/posts/{post_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Delete a post (soft)',
    )
    @db_context_session(auto_commit=True)
    async def delete_post(self, post_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        blog, post = await access.load_post(
            session, scope, post_id, 'delete', writable=True
        )
        await svc.delete_post(session, scope, blog, post)

    @put(
        '/posts/{post_id}/draft',
        summary='Autosave title + body into the draft revision (Blog-0101)',
    )
    @db_context_session(auto_commit=True)
    async def save_draft(
        self, post_id: str, data: BlogDraftSave, session: DBAsyncScopedSession
    ) -> BlogDraftOut:
        scope = await current_scope()
        blog, post = await access.load_post(session, scope, post_id, writable=True)
        await access.require_edit(session, scope, blog, post)
        revision, created = await svc.save_draft(session, scope, blog, post, data)
        return _draft_out(scope, blog, post, revision, created=created)

    @get('/posts/{post_id}/revisions', summary='Revisions, newest first')
    @db_context_session
    async def list_revisions(
        self, post_id: str, session: DBAsyncScopedSession, limit: int = 50
    ) -> list[BlogRevisionOut]:
        scope = await current_scope()
        _, post = await access.load_post(session, scope, post_id)
        return await svc.list_revisions(session, post, limit)

    @get(
        '/posts/{post_id}/revisions/{revision_id}',
        summary='A revision with its body and metadata snapshot',
    )
    @db_context_session
    async def get_revision(
        self, post_id: str, revision_id: str, session: DBAsyncScopedSession
    ) -> BlogRevisionDetailOut:
        scope = await current_scope()
        _, post = await access.load_post(session, scope, post_id)
        return await svc.get_revision(session, post, revision_id)

    @post(
        '/posts/{post_id}/revisions/{revision_id}/restore',
        summary='Copy a revision (title + body) into the draft',
    )
    @db_context_session(auto_commit=True)
    async def restore_revision(
        self, post_id: str, revision_id: str, session: DBAsyncScopedSession
    ) -> BlogDraftOut:
        scope = await current_scope()
        blog, post = await access.load_post(session, scope, post_id, writable=True)
        await access.require_edit(session, scope, blog, post)
        revision = await svc.restore_revision(session, scope, blog, post, revision_id)
        return _draft_out(scope, blog, post, revision, created=True)

    @post(
        '/posts/{post_id}/lock',
        summary='Take / refresh the soft lock (force = take over)',
    )
    @db_context_session(auto_commit=True)
    async def lock(
        self, post_id: str, data: BlogLockRequest, session: DBAsyncScopedSession
    ) -> BlogLockOut:
        scope = await current_scope()
        blog, post = await access.load_post(session, scope, post_id, writable=True)
        await access.require_edit(session, scope, blog, post)
        locked, holder = await svc.lock_post(session, scope, post, force=data.force)
        names = await user_names(session, [holder])
        return BlogLockOut(
            locked=locked,
            holder_id=str(holder) if holder else None,
            holder_name=names.get(holder) if holder else None,
            expires_at=post.lock_expires_at,
        )

    @delete(
        '/posts/{post_id}/lock',
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Release the caller's lock",
    )
    @db_context_session(auto_commit=True)
    async def unlock(self, post_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        _, post = await access.load_post(session, scope, post_id)
        await svc.unlock_post(session, scope, post)
