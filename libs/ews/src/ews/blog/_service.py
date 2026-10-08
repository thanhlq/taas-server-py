"""Blogs of an organization (Blog §3) and helpers of the blog services: free slugs, media checks. Every change of
a blog's public output rebuilds its release (``_release.rebuild_release``); delete / archive remove its public
media, restore copies them again.

``session`` = the request's DB session (``db_context_session``), ``scope`` = the verified caller. Posts live in
``_posts``, the editorial workflow in ``_workflow``, categories / tags / authors in ``_taxonomy``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Collection
from typing import Any
from uuid import UUID

import msgspec
from db.models.blog import Blog, BlogAuthor, BlogPost
from db.models.media import MediaAsset
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import ConflictException, parse_uuid, path_segment_taken, utcnow

from ._access import BLOG, readable_blog_ids
from ._release import blog_url, rebuild_release, remove_blog_media, republish_media
from ._rules import (
    DEFAULT_SETTINGS,
    blog_slug_error,
    clean_settings,
    locale_error,
    slugify,
    term_slug_error,
)
from .schemas import BlogCreate, BlogOut, BlogUpdate

logger = logging.getLogger(__name__)
"""Editorial events (publish, unpublish, delete) are logged here until the audit store lands."""


# --- helpers ----------------------------------------------------------------------------------------


async def slug_in_use(
    session: DBAsyncScopedSession,
    model: Any,
    blog_id: UUID,
    slug: str,
    *,
    exclude: UUID | None = None,
) -> bool:
    """A live row of ``model`` (post, category, tag, author) of the blog uses ``slug``."""
    stmt = select(model.id).where(model.blog_id == blog_id, model.slug == slug)
    if hasattr(model, 'deleted_at'):
        stmt = stmt.where(model.deleted_at.is_(None))
    if exclude is not None:
        stmt = stmt.where(model.id != exclude)
    return (await session.scalar(stmt.limit(1))) is not None


async def free_slug(
    session: DBAsyncScopedSession,
    model: Any,
    blog_id: UUID,
    base: str,
    *,
    max_len: int = 80,
    exclude: UUID | None = None,
    reserved: Collection[str] = (),
) -> str:
    """``base``, else ``base-2``, ``base-3`` … unused in the blog (``exclude`` = the row being renamed) and not
    ``reserved``."""
    slug, n = base, 2
    while slug in reserved or await slug_in_use(
        session, model, blog_id, slug, exclude=exclude
    ):
        suffix = f'-{n}'
        slug = f'{base[: max_len - len(suffix)].rstrip("-")}{suffix}'
        n += 1
    return slug


async def pick_slug(
    session: DBAsyncScopedSession,
    model: Any,
    blog_id: UUID,
    wanted: str | None,
    fallback_text: str,
    *,
    default: str,
    exclude: UUID | None = None,
    check: Callable[[str], str | None] = term_slug_error,
    reserved: Collection[str] = (),
) -> str:
    """An explicit slug (``check`` → 400; 409 ``slug_taken`` when used) or a free one derived from
    ``fallback_text`` (``ews.shared.slugify``, Blog-0106) avoiding ``reserved``."""
    if wanted:
        if error := check(wanted):
            raise ClientException(detail=error)
        if await slug_in_use(session, model, blog_id, wanted, exclude=exclude):
            raise ConflictException(
                detail=f'the slug "{wanted}" is already used',
                extra={'code': 'slug_taken'},
            )
        return wanted
    return await free_slug(
        session,
        model,
        blog_id,
        slugify(fallback_text, 80) or default,
        exclude=exclude,
        reserved=reserved,
    )


async def check_asset(
    session: DBAsyncScopedSession, scope: RequestScope, value: object, what: str
) -> UUID:
    """A media library asset of the request's organization (not in the trash), else 400."""
    raw = str(value)
    aid = parse_uuid(raw.removeprefix('asset:'), what, not_found=False)
    found = await session.scalar(
        select(MediaAsset.id).where(
            MediaAsset.id == aid,
            MediaAsset.tenant_id == scope.tenant_id,
            MediaAsset.organization_id == scope.organization_id,
            MediaAsset.deleted_at.is_(None),
        )
    )
    if found is None:
        raise ClientException(detail=f'{what} is not a file of the media library')
    return aid


def text_field(
    value: str | None, what: str, max_len: int, *, required: bool = False
) -> str | None:
    """Trimmed single text value (``None`` / empty → ``None`` unless ``required``)."""
    clean = (value or '').strip()
    if not clean:
        if required:
            raise ClientException(detail=f'{what} is required')
        return None
    if len(clean) > max_len:
        raise ClientException(detail=f'{what} must be at most {max_len} characters')
    return clean


# --- blogs ------------------------------------------------------------------------------------------


def blog_settings(blog: Blog) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(blog.settings or {})}


def blog_out(
    blog: Blog,
    org_slug: str,
    *,
    post_count: int = 0,
    role: str | None = None,
    permissions: set[str] | None = None,
) -> BlogOut:
    return BlogOut(
        id=str(blog.id),
        slug=blog.slug,
        public_url=blog_url(org_slug, blog.slug),
        name=blog.name,
        description=blog.description,
        locale=blog.locale,
        mount=blog.mount,  # type: ignore[arg-type]
        status=blog.status,  # type: ignore[arg-type]
        settings=blog_settings(blog),
        post_count=post_count,
        role=role,
        permissions=sorted(permissions or ()),
        created_by=str(blog.created_by) if blog.created_by else None,
        created_at=blog.created_at,
        updated_at=blog.updated_at,
    )


async def _post_counts(
    session: DBAsyncScopedSession, blog_ids: list[UUID]
) -> dict[UUID, int]:
    if not blog_ids:
        return {}
    rows = await session.execute(
        select(BlogPost.blog_id, func.count())
        .where(BlogPost.blog_id.in_(blog_ids), BlogPost.deleted_at.is_(None))
        .group_by(BlogPost.blog_id)
    )
    return dict(rows.tuples().all())


async def blog_detail(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog
) -> BlogOut:
    counts = await _post_counts(session, [blog.id])
    role = None if scope.is_dev else await BLOG.role_of(scope.user_id, blog.id)
    permissions = await BLOG.permissions(scope, blog.id)
    return blog_out(
        blog,
        scope.organization.slug,
        post_count=counts.get(blog.id, 0),
        role=role,
        permissions=permissions,
    )


async def list_blogs(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[BlogOut]:
    """Blogs of the organization the caller can read (Blog §3), by name."""
    readable = await readable_blog_ids(scope)
    stmt = select(Blog).where(
        Blog.tenant_id == scope.tenant_id,
        Blog.organization_id == scope.organization_id,
        Blog.deleted_at.is_(None),
    )
    if readable is not None:
        if not readable:
            return []
        stmt = stmt.where(Blog.id.in_(readable))
    blogs = list(
        await session.scalars(stmt.order_by(func.lower(Blog.name), Blog.created_at))
    )
    counts = await _post_counts(session, [b.id for b in blogs])
    roles = {} if scope.is_dev else await BLOG.shared_with(scope.user_id)
    return [
        blog_out(
            b,
            scope.organization.slug,
            post_count=counts.get(b.id, 0),
            role=roles.get(b.id),
        )
        for b in blogs
    ]


async def _blog_slug_taken(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    slug: str,
    exclude: UUID | None = None,
) -> bool:
    """A live blog or site of the organization uses the slug (both are served at ``<org host>/<slug>``)."""
    return await path_segment_taken(
        session, scope.organization_id, slug, exclude=exclude
    )


async def _blog_slug(
    session: DBAsyncScopedSession, scope: RequestScope, name: str, wanted: str | None
) -> str:
    if wanted:
        if error := blog_slug_error(wanted):
            raise ClientException(detail=error)
        if await _blog_slug_taken(session, scope, wanted):
            raise ConflictException(
                detail=f'"{wanted}" is already used by a blog or site',
                extra={'code': 'slug_taken'},
            )
        return wanted
    base = slugify(name, 36)
    if blog_slug_error(base):
        base = 'blog'
    slug, n = base, 2
    while await _blog_slug_taken(session, scope, slug):
        slug, n = f'{base}-{n}', n + 1
    return slug


async def _check_settings(
    session: DBAsyncScopedSession, blog_id: UUID | None, settings: dict[str, Any]
) -> None:
    author_id = settings.get('default_author_id')
    if author_id is None:
        return
    found = None
    if blog_id is not None:
        found = await session.scalar(
            select(BlogAuthor.id).where(
                BlogAuthor.id == UUID(author_id), BlogAuthor.blog_id == blog_id
            )
        )
    if found is None:
        raise ClientException(
            detail='settings.default_author_id is not an author of this blog'
        )


async def create_blog(
    session: DBAsyncScopedSession, scope: RequestScope, data: BlogCreate
) -> Blog:
    """New blog in the request's organization; the creator becomes its ``blog_admin``."""
    name = text_field(data.name, 'name', 120, required=True)
    assert name is not None
    if error := locale_error(data.locale):
        raise ClientException(detail=error)
    settings = clean_settings(data.settings or {})
    await _check_settings(session, None, settings)
    blog = Blog(
        id=uuid.uuid7(),
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        slug=await _blog_slug(session, scope, name, data.slug),
        name=name,
        description=text_field(data.description, 'description', 500),
        locale=data.locale,
        mount='system',
        settings=settings,
        status='active',
        created_by=scope.user_id,
    )
    session.add(blog)
    await session.flush()
    await BLOG.grant_creator(scope.user_id, blog.id)
    await rebuild_release(session, blog)  # the blog home answers (empty) from the start
    logger.info(
        'blog.created', extra={'blog_id': str(blog.id), 'actor': str(scope.user_id)}
    )
    return blog


async def update_blog(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, data: BlogUpdate
) -> Blog:
    if data.name is not None:
        blog.name = text_field(data.name, 'name', 120, required=True) or blog.name
    if data.slug is not None and data.slug != blog.slug:
        if error := blog_slug_error(data.slug):
            raise ClientException(detail=error)
        if await _blog_slug_taken(session, scope, data.slug, exclude=blog.id):
            raise ConflictException(
                detail=f'"{data.slug}" is already used by a blog or site',
                extra={'code': 'slug_taken'},
            )
        blog.slug = data.slug
    if data.description is not msgspec.UNSET:
        blog.description = text_field(data.description, 'description', 500)  # type: ignore[arg-type]
    if data.locale is not None:
        if error := locale_error(data.locale):
            raise ClientException(detail=error)
        blog.locale = data.locale
    if data.mount is not None and data.mount != blog.mount:
        if data.mount == 'site':
            raise ClientException(
                detail='mounting a blog on a site arrives with publishing (B3)'
            )
        blog.mount = data.mount
    if data.settings is not None:
        merged = {**(blog.settings or {}), **data.settings}
        settings = clean_settings(merged)
        await _check_settings(session, blog.id, settings)
        blog.settings = settings
    restored = archived = False
    if data.status is not None and data.status != blog.status:
        restored, archived = data.status == 'active', data.status == 'archived'
        blog.status = data.status
    blog.updated_at = utcnow()
    await session.flush()
    if archived:  # off the public hosts: no route, no public copies
        await remove_blog_media(blog)
    else:
        if restored:
            await republish_media(session, blog)
        await rebuild_release(session, blog)
    return blog


async def delete_blog(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog
) -> None:
    """Soft delete (the slug becomes free); every role on the blog is revoked."""
    blog.deleted_at = utcnow()
    await session.flush()
    await BLOG.forget(blog.id)
    await remove_blog_media(blog)
    logger.info(
        'blog.deleted', extra={'blog_id': str(blog.id), 'actor': str(scope.user_id)}
    )
