"""Who may do what on a blog: ``ews.access.ObjectAccess`` on ``blog:<id>`` → organization chain → tenant.

Blogs belong to the request's organization: a blog (or post) of another organization, or one the caller cannot
read, is a 404; readable without the action → 403. Posts add the own-post rule (``blog.post:update_own``):
an author edits the posts it created or is credited on (``_rules.is_own``).
"""

from __future__ import annotations

from uuid import UUID

from db.models.blog import Blog, BlogAuthor, BlogPost, BlogPostAuthor
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException, PermissionDeniedException
from sqlalchemy import func, select

from ews.access import ObjectAccess
from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, parse_uuid

from ._rules import can_edit, is_own

BLOG_RES = EwsResources.BLOG_BLOG.value
MEMBER_RES = EwsResources.BLOG_MEMBER.value
POST_RES = EwsResources.BLOG_POST.value
TAXONOMY_RES = EwsResources.BLOG_TAXONOMY.value

BLOG = ObjectAccess('blog', BLOG_RES, 'blog', default_role='blog_author')
"""Roles ``blog_admin`` · ``blog_editor`` · ``blog_author`` · ``blog_viewer`` on ``blog:<id>``."""


def _check_writable(blog: Blog) -> None:
    if blog.status == 'archived':
        raise ConflictException(
            detail='the blog is archived', extra={'code': 'blog_archived'}
        )


async def load_blog(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog_id: object,
    resource: str = BLOG_RES,
    action: str = 'read',
    *,
    writable: bool = False,
) -> Blog:
    """A blog of the request's organization the caller may ``resource:action`` (404 / 403); ``writable``:
    409 ``blog_archived`` on an archived blog."""
    bid = parse_uuid(blog_id, 'blog')
    blog = await session.scalar(
        select(Blog).where(
            Blog.id == bid,
            Blog.tenant_id == scope.tenant_id,
            Blog.organization_id == scope.organization_id,
            Blog.deleted_at.is_(None),
        )
    )
    if blog is None:
        raise NotFoundException(detail='blog not found')
    await BLOG.check(scope, blog.id, resource, action, what='blog')
    if writable:
        _check_writable(blog)
    return blog


async def load_post(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    post_id: object,
    action: str = 'read',
    *,
    writable: bool = False,
) -> tuple[Blog, BlogPost]:
    """A live post (and its blog) of the request's organization the caller may ``blog.post:<action>``."""
    pid = parse_uuid(post_id, 'post')
    row = (
        await session.execute(
            select(BlogPost, Blog)
            .join(Blog, Blog.id == BlogPost.blog_id)
            .where(
                BlogPost.id == pid,
                BlogPost.tenant_id == scope.tenant_id,
                BlogPost.deleted_at.is_(None),
                Blog.organization_id == scope.organization_id,
                Blog.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise NotFoundException(detail='post not found')
    post, blog = row
    await BLOG.check(scope, blog.id, POST_RES, action, what='post')
    if writable:
        _check_writable(blog)
    return blog, post


async def author_user_ids(
    session: DBAsyncScopedSession, post_ids: list[UUID]
) -> dict[UUID, set[UUID]]:
    """``{post id: user ids of its author profiles}``."""
    if not post_ids:
        return {}
    rows = await session.execute(
        select(BlogPostAuthor.post_id, BlogAuthor.user_id)
        .join(BlogAuthor, BlogAuthor.id == BlogPostAuthor.author_id)
        .where(BlogPostAuthor.post_id.in_(post_ids), BlogAuthor.user_id.is_not(None))
    )
    out: dict[UUID, set[UUID]] = {}
    for post_id, user_id in rows.all():
        out.setdefault(post_id, set()).add(user_id)
    return out


async def is_own_post(
    session: DBAsyncScopedSession, scope: RequestScope, post: BlogPost
) -> bool:
    users = (await author_user_ids(session, [post.id])).get(post.id, set())
    return is_own(scope.user_id, post.created_by, users)


async def require_edit(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> None:
    """403 unless the caller holds ``blog.post:update``, or ``update_own`` and the post is its own."""
    if await BLOG.allowed(scope, blog.id, POST_RES, 'update'):
        return
    if await BLOG.allowed(scope, blog.id, POST_RES, 'update_own') and await is_own_post(
        session, scope, post
    ):
        return
    raise PermissionDeniedException(
        detail='missing permission blog.post:update (authors edit their own posts)'
    )


async def edit_permission(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    permissions: set[str],
) -> bool:
    """``can_edit`` flag of a post for the caller (permissions = ``BLOG.permissions``)."""
    if 'blog.post:update' in permissions:
        return True
    return can_edit(permissions, await is_own_post(session, scope, post))


async def readable_blog_ids(scope: RequestScope) -> set[UUID] | None:
    """``None`` = every blog of the organization (organization-level read), else the blogs with a role."""
    if await is_allowed(scope, BLOG_RES, 'read'):
        return None
    return set(await BLOG.shared_with(scope.user_id))


async def can_open_app(
    session: DBAsyncScopedSession, scope: RequestScope
) -> tuple[bool, bool]:
    """``(allowed, can_create)`` of ``GET /access``: an organization-level ``blog.*`` right or a role on one
    of the organization's blogs."""
    can_create = await is_allowed(scope, BLOG_RES, 'create')
    readable = await readable_blog_ids(scope)
    if can_create or readable is None:
        return True, can_create
    if not readable:
        return False, False
    count = await session.scalar(
        select(func.count())
        .select_from(Blog)
        .where(
            Blog.id.in_(readable),
            Blog.tenant_id == scope.tenant_id,
            Blog.organization_id == scope.organization_id,
            Blog.deleted_at.is_(None),
        )
    )
    return bool(count), False
