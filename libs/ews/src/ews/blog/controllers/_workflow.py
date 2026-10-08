"""``/api/v1/blog/posts/{id}/…`` — editorial workflow (Blog-0102 / 0103): submit, request changes, approve,
publish / update, schedule, unpublish, archive."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, post

from ews.security import current_scope

from .. import _access as access
from .. import _posts as posts
from .. import _workflow as flow
from .._access import BLOG, POST_RES
from ..schemas import BlogApproveIn, BlogCommentIn, BlogPostDetailOut, BlogScheduleIn


class BlogWorkflowController(BaseController):
    api_prefix = '/api/v1/blog/posts/{post_id}'
    tags = ('Blog',)

    @post(
        '/submit',
        summary='Submit for review (blog.post:submit on an own post, or blog.post:update)',
    )
    @db_context_session(auto_commit=True)
    async def submit(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'submit', writable=True
        )
        await access.require_edit(session, scope, blog, item)
        await flow.submit(session, scope, blog, item)
        return await posts.post_detail(session, scope, blog, item)

    @post(
        '/request-changes',
        summary='Back to draft with a comment for the author (blog.post:review)',
    )
    @db_context_session(auto_commit=True)
    async def request_changes(
        self, post_id: str, data: BlogCommentIn, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'review', writable=True
        )
        await flow.request_changes(session, scope, blog, item, data.comment)
        return await posts.post_detail(session, scope, blog, item)

    @post(
        '/approve',
        summary='Approve a post in review: publish now or schedule (review + publish)',
    )
    @db_context_session(auto_commit=True)
    async def approve(
        self, post_id: str, data: BlogApproveIn, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'review', writable=True
        )
        await BLOG.require(scope, blog.id, POST_RES, 'publish')
        await flow.approve(session, scope, blog, item, data.scheduled_at, data.timezone)
        return await posts.post_detail(session, scope, blog, item)

    @post('/publish', summary='Publish the draft now (Update when already published)')
    @db_context_session(auto_commit=True)
    async def publish(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'publish', writable=True
        )
        await flow.publish(session, scope, blog, item)
        return await posts.post_detail(session, scope, blog, item)

    @post('/schedule', summary='Publish at a date and time (timezone)')
    @db_context_session(auto_commit=True)
    async def schedule(
        self, post_id: str, data: BlogScheduleIn, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'publish', writable=True
        )
        await flow.schedule(
            session, scope, blog, item, data.scheduled_at, data.timezone
        )
        return await posts.post_detail(session, scope, blog, item)

    @post('/unpublish', summary='Take off the blog (or cancel a schedule)')
    @db_context_session(auto_commit=True)
    async def unpublish(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'publish', writable=True
        )
        await flow.unpublish(session, scope, blog, item)
        return await posts.post_detail(session, scope, blog, item)

    @post('/archive', summary='Archive (off the blog, hidden from the default list)')
    @db_context_session(auto_commit=True)
    async def archive(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'publish', writable=True
        )
        await flow.archive(session, scope, blog, item)
        return await posts.post_detail(session, scope, blog, item)

    @post('/unarchive', summary='Back to draft (or unpublished)')
    @db_context_session(auto_commit=True)
    async def unarchive(
        self, post_id: str, session: DBAsyncScopedSession
    ) -> BlogPostDetailOut:
        scope = await current_scope()
        blog, item = await access.load_post(
            session, scope, post_id, 'publish', writable=True
        )
        await flow.unarchive(session, scope, blog, item)
        return await posts.post_detail(session, scope, blog, item)
