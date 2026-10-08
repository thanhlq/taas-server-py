"""Categories (flat, ordered), tags and author profiles of a blog (Blog-0104). Changing them needs
``blog.taxonomy:manage``; reading ``blog.taxonomy:read``.

Deleting a category leaves its posts without category, deleting a tag removes it from its posts; an author
still credited on a post cannot be deleted (409 ``author_in_use``). Every change rebuilds the blog's release
(a new one only when the public output changed).
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import msgspec
from db.models.blog import (
    Blog,
    BlogAuthor,
    BlogCategory,
    BlogPost,
    BlogPostAuthor,
    BlogPostTag,
    BlogTag,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import func, select, text

from ews.media import record_usages
from ews.security import RequestScope
from ews.shared import ConflictException, clean_seo, parse_uuid, utcnow

from ._release import rebuild_release
from ._rules import clean_links
from ._service import check_asset, pick_slug, text_field
from .schemas import (
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

MAX_CATEGORIES = 200
MAX_TAGS = 2000
MAX_AUTHORS = 500


async def _get(
    session: DBAsyncScopedSession, model: Any, blog: Blog, item_id: object, what: str
) -> Any:
    iid = parse_uuid(item_id, what)
    item = await session.scalar(
        select(model).where(model.id == iid, model.blog_id == blog.id)
    )
    if item is None:
        raise NotFoundException(detail=f'{what} not found')
    return item


async def _count(session: DBAsyncScopedSession, model: Any, blog: Blog) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(model).where(model.blog_id == blog.id)
        )
        or 0
    )


def _live_posts(blog: Blog) -> Any:
    return select(BlogPost.id).where(
        BlogPost.blog_id == blog.id, BlogPost.deleted_at.is_(None)
    )


# --- categories ---------------------------------------------------------------------------------------


def _category_out(c: BlogCategory, post_count: int = 0) -> BlogCategoryOut:
    return BlogCategoryOut(
        id=str(c.id),
        slug=c.slug,
        name=c.name,
        description=c.description,
        position=c.position,
        seo=dict(c.seo or {}),
        post_count=post_count,
    )


async def _categories(session: DBAsyncScopedSession, blog: Blog) -> list[BlogCategory]:
    return list(
        await session.scalars(
            select(BlogCategory)
            .where(BlogCategory.blog_id == blog.id)
            .order_by(BlogCategory.position, BlogCategory.created_at)
        )
    )


async def list_categories(
    session: DBAsyncScopedSession, blog: Blog
) -> list[BlogCategoryOut]:
    rows = await session.execute(
        select(BlogPost.category_id, func.count())
        .where(
            BlogPost.blog_id == blog.id,
            BlogPost.deleted_at.is_(None),
            BlogPost.category_id.is_not(None),
        )
        .group_by(BlogPost.category_id)
    )
    counts = dict(rows.tuples().all())
    return [
        _category_out(c, counts.get(c.id, 0)) for c in await _categories(session, blog)
    ]


async def create_category(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    data: BlogCategoryCreate,
) -> BlogCategoryOut:
    name = text_field(data.name, 'name', 120, required=True)
    assert name is not None
    existing = await _categories(session, blog)
    if len(existing) >= MAX_CATEGORIES:
        raise ConflictException(
            detail=f'a blog has at most {MAX_CATEGORIES} categories',
            extra={'code': 'limit'},
        )
    category = BlogCategory(
        id=uuid.uuid7(),
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        slug=await pick_slug(
            session, BlogCategory, blog.id, data.slug, name, default='category'
        ),
        name=name,
        description=text_field(data.description, 'description', 500),
        position=max((c.position for c in existing), default=-1) + 1,
        seo=clean_seo(data.seo),
    )
    session.add(category)
    await session.flush()
    await rebuild_release(session, blog)
    return _category_out(category)


async def update_category(
    session: DBAsyncScopedSession,
    blog: Blog,
    category_id: object,
    data: BlogCategoryUpdate,
) -> BlogCategoryOut:
    category: BlogCategory = await _get(
        session, BlogCategory, blog, category_id, 'category'
    )
    if data.name is not None:
        category.name = (
            text_field(data.name, 'name', 120, required=True) or category.name
        )
    if data.slug is not None and data.slug != category.slug:
        category.slug = await pick_slug(
            session,
            BlogCategory,
            blog.id,
            data.slug,
            category.name,
            default='category',
            exclude=category.id,
        )
    if data.description is not msgspec.UNSET:
        category.description = text_field(data.description, 'description', 500)  # type: ignore[arg-type]
    if data.seo is not None:
        category.seo = clean_seo(data.seo)
    if data.position is not None:
        others = [c for c in await _categories(session, blog) if c.id != category.id]
        others.insert(max(0, min(data.position, len(others))), category)
        for i, c in enumerate(others):
            c.position = i
    category.updated_at = utcnow()
    await session.flush()
    await rebuild_release(session, blog)
    return _category_out(category)


async def delete_category(
    session: DBAsyncScopedSession, blog: Blog, category_id: object
) -> None:
    """Its posts keep no category (``ON DELETE SET NULL``)."""
    category = await _get(session, BlogCategory, blog, category_id, 'category')
    await session.delete(category)
    await session.flush()
    await rebuild_release(session, blog)


# --- tags ---------------------------------------------------------------------------------------------


def _tag_out(t: BlogTag, post_count: int = 0) -> BlogTagOut:
    return BlogTagOut(id=str(t.id), slug=t.slug, name=t.name, post_count=post_count)


async def list_tags(
    session: DBAsyncScopedSession, blog: Blog, q: str | None = None
) -> list[BlogTagOut]:
    stmt = select(BlogTag).where(BlogTag.blog_id == blog.id)
    if q and q.strip():
        stmt = stmt.where(
            func.lower(BlogTag.name).contains(q.strip().lower(), autoescape=True)
        )
    tags = list(await session.scalars(stmt.order_by(func.lower(BlogTag.name))))
    rows = await session.execute(
        select(BlogPostTag.tag_id, func.count())
        .where(BlogPostTag.post_id.in_(_live_posts(blog)))
        .group_by(BlogPostTag.tag_id)
    )
    counts = dict(rows.tuples().all())
    return [_tag_out(t, counts.get(t.id, 0)) for t in tags]


async def create_tag(
    session: DBAsyncScopedSession, blog: Blog, data: BlogTagCreate
) -> BlogTagOut:
    name = text_field(data.name, 'name', 80, required=True)
    assert name is not None
    if await _count(session, BlogTag, blog) >= MAX_TAGS:
        raise ConflictException(
            detail=f'a blog has at most {MAX_TAGS} tags', extra={'code': 'limit'}
        )
    tag = BlogTag(
        id=uuid.uuid7(),
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        slug=await pick_slug(session, BlogTag, blog.id, data.slug, name, default='tag'),
        name=name,
    )
    session.add(tag)
    await session.flush()
    await rebuild_release(session, blog)
    return _tag_out(tag)


async def update_tag(
    session: DBAsyncScopedSession, blog: Blog, tag_id: object, data: BlogTagUpdate
) -> BlogTagOut:
    tag: BlogTag = await _get(session, BlogTag, blog, tag_id, 'tag')
    if data.name is not None:
        tag.name = text_field(data.name, 'name', 80, required=True) or tag.name
    if data.slug is not None and data.slug != tag.slug:
        tag.slug = await pick_slug(
            session,
            BlogTag,
            blog.id,
            data.slug,
            tag.name,
            default='tag',
            exclude=tag.id,
        )
    tag.updated_at = utcnow()
    await session.flush()
    await rebuild_release(session, blog)
    return _tag_out(tag)


async def delete_tag(session: DBAsyncScopedSession, blog: Blog, tag_id: object) -> None:
    """Removed from its posts (``ON DELETE CASCADE``)."""
    tag = await _get(session, BlogTag, blog, tag_id, 'tag')
    await session.delete(tag)
    await session.flush()
    await rebuild_release(session, blog)


# --- authors ------------------------------------------------------------------------------------------


def author_out(a: BlogAuthor, post_count: int = 0) -> BlogAuthorOut:
    return BlogAuthorOut(
        id=str(a.id),
        slug=a.slug,
        display_name=a.display_name,
        avatar_asset_id=str(a.avatar_asset_id) if a.avatar_asset_id else None,
        bio=a.bio,
        links=list(a.links or []),
        user_id=str(a.user_id) if a.user_id else None,
        post_count=post_count,
    )


async def list_authors(
    session: DBAsyncScopedSession, blog: Blog
) -> list[BlogAuthorOut]:
    authors = list(
        await session.scalars(
            select(BlogAuthor)
            .where(BlogAuthor.blog_id == blog.id)
            .order_by(func.lower(BlogAuthor.display_name))
        )
    )
    rows = await session.execute(
        select(BlogPostAuthor.author_id, func.count())
        .where(BlogPostAuthor.post_id.in_(_live_posts(blog)))
        .group_by(BlogPostAuthor.author_id)
    )
    counts = dict(rows.tuples().all())
    return [author_out(a, counts.get(a.id, 0)) for a in authors]


async def _organization_user(
    session: DBAsyncScopedSession, scope: RequestScope, value: object
) -> UUID:
    """A member of the request's organization (or of a sub-organization), else 400."""
    uid = parse_uuid(value, 'user_id', not_found=False)
    found = await session.scalar(
        text(
            'select m.user_id from taas_organization_members m '
            'join taas_organizations o on o.id = m.organization_id '
            'where m.user_id = :u and m.tenant_id = :t and o.path like :path limit 1'
        ),
        {'u': uid, 't': scope.tenant_id, 'path': f'%/{scope.organization_id}/%'},
    )
    if found is None:
        raise ClientException(detail='user_id is not a member of this organization')
    return uid


async def _check_user_free(
    session: DBAsyncScopedSession,
    blog: Blog,
    user_id: UUID,
    exclude: UUID | None = None,
) -> None:
    stmt = select(BlogAuthor.id).where(
        BlogAuthor.blog_id == blog.id, BlogAuthor.user_id == user_id
    )
    if exclude is not None:
        stmt = stmt.where(BlogAuthor.id != exclude)
    if await session.scalar(stmt.limit(1)) is not None:
        raise ConflictException(
            detail='this user already has an author profile',
            extra={'code': 'author_exists'},
        )


async def _avatar_usage(
    session: DBAsyncScopedSession, blog: Blog, author: BlogAuthor
) -> None:
    await record_usages(
        session,
        blog.tenant_id,
        app='blog',
        ref_type='author',
        ref_id=author.id,
        label=f'{blog.name} › {author.display_name}',
        asset_ids=[author.avatar_asset_id] if author.avatar_asset_id else [],
    )


async def create_author(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    data: BlogAuthorCreate,
) -> BlogAuthorOut:
    name = text_field(data.display_name, 'display_name', 120, required=True)
    assert name is not None
    if await _count(session, BlogAuthor, blog) >= MAX_AUTHORS:
        raise ConflictException(
            detail=f'a blog has at most {MAX_AUTHORS} authors', extra={'code': 'limit'}
        )
    user_id = (
        await _organization_user(session, scope, data.user_id) if data.user_id else None
    )
    if user_id is not None:
        await _check_user_free(session, blog, user_id)
    author = BlogAuthor(
        id=uuid.uuid7(),
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        slug=await pick_slug(
            session, BlogAuthor, blog.id, data.slug, name, default='author'
        ),
        display_name=name,
        avatar_asset_id=await check_asset(
            session, scope, data.avatar_asset_id, 'avatar_asset_id'
        )
        if data.avatar_asset_id
        else None,
        bio=text_field(data.bio, 'bio', 2000),
        links=clean_links(data.links),
        user_id=user_id,
    )
    session.add(author)
    await session.flush()
    await _avatar_usage(session, blog, author)
    await rebuild_release(session, blog)
    return author_out(author)


async def update_author(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    author_id: object,
    data: BlogAuthorUpdate,
) -> BlogAuthorOut:
    author: BlogAuthor = await _get(session, BlogAuthor, blog, author_id, 'author')
    if data.display_name is not None:
        author.display_name = (
            text_field(data.display_name, 'display_name', 120, required=True)
            or author.display_name
        )
    if data.slug is not None and data.slug != author.slug:
        author.slug = await pick_slug(
            session,
            BlogAuthor,
            blog.id,
            data.slug,
            author.display_name,
            default='author',
            exclude=author.id,
        )
    if data.avatar_asset_id is not msgspec.UNSET:
        author.avatar_asset_id = (
            await check_asset(session, scope, data.avatar_asset_id, 'avatar_asset_id')
            if data.avatar_asset_id
            else None
        )
    if data.bio is not msgspec.UNSET:
        author.bio = text_field(data.bio, 'bio', 2000)  # type: ignore[arg-type]
    if data.links is not None:
        author.links = clean_links(data.links)
    if data.user_id is not msgspec.UNSET:
        if data.user_id:
            uid = await _organization_user(session, scope, data.user_id)
            await _check_user_free(session, blog, uid, exclude=author.id)
            author.user_id = uid
        else:
            author.user_id = None
    author.updated_at = utcnow()
    await session.flush()
    await _avatar_usage(session, blog, author)
    await rebuild_release(session, blog)
    return author_out(author)


async def delete_author(
    session: DBAsyncScopedSession, blog: Blog, author_id: object
) -> None:
    author = await _get(session, BlogAuthor, blog, author_id, 'author')
    used = await session.scalar(
        select(func.count())
        .select_from(BlogPostAuthor)
        .where(
            BlogPostAuthor.author_id == author.id,
            BlogPostAuthor.post_id.in_(_live_posts(blog)),
        )
    )
    if used:
        raise ConflictException(
            detail=f'this author is credited on {used} post(s): change their byline first',
            extra={'code': 'author_in_use'},
        )
    await record_usages(
        session,
        blog.tenant_id,
        app='blog',
        ref_type='author',
        ref_id=author.id,
        label=None,
        asset_ids=[],
    )
    await session.delete(author)
    await session.flush()
    await rebuild_release(session, blog)
