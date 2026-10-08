"""Posts: create, list (filters + counts per status), metadata, draft autosave, revisions, soft lock, delete
(Blog-0100 / 0101 / 0104 / 0300), addresses (Blog-0106…0110).

Body = site document in revisions: ``draft_revision_id`` is the working copy (autosaves of the same user and
source within ``REVISION_WINDOW`` update it in place), ``published_revision_id`` the live one. Editing a published
post — body or metadata — starts a new draft revision; the live one changes only on publish (``_workflow``).

Address: the slug follows the title while ``slug_auto`` and the post was never published; a hand-made slug turns
``slug_auto`` off, ``""`` regenerates it. After the first publication a change keeps the old slug in
``former_slugs`` (301) and — the address being public at once — rebuilds the blog's release when the post is live.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable
from typing import Any
from uuid import UUID

import msgspec
from db.models.blog import (
    Blog,
    BlogAuthor,
    BlogCategory,
    BlogPost,
    BlogPostAuthor,
    BlogPostRevision,
    BlogPostTag,
    BlogTag,
)
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    ValidationException,
)
from sqlalchemy import delete, func, or_, select

from ews.media import record_usages
from ews.security import RequestScope
from ews.shared import ConflictException, clean_seo, parse_uuid, user_names, utcnow
from ews.sites._document import (
    asset_ids,
    empty_document,
    migrate_document,
    validate_document,
)

from ._access import BLOG
from ._release import blog_url, is_live, rebuild_release
from ._rules import (
    LOCK_TTL,
    POST_STATUSES,
    RESERVED_POST_SLUGS,
    REVISION_WINDOW,
    can_edit,
    is_own,
    post_slug_error,
    reading_time,
    remember_slug,
    slugify,
)
from ._service import check_asset, free_slug, logger, pick_slug, text_field
from .schemas import (
    BlogAuthorRef,
    BlogDraftSave,
    BlogPostCreate,
    BlogPostDetailOut,
    BlogPostListOut,
    BlogPostOut,
    BlogPostUpdate,
    BlogRevisionDetailOut,
    BlogRevisionOut,
    BlogTermRef,
)

MAX_TAGS = 20
MAX_AUTHORS = 10
_SORTS = {
    'updated': (BlogPost.updated_at, 'desc'),
    'created': (BlogPost.created_at, 'desc'),
    'published': (BlogPost.published_at, 'desc'),
    'scheduled': (BlogPost.scheduled_at, 'asc'),
    'title': (func.lower(BlogPost.title), 'asc'),
}


def invalid_document(issues: Iterable[Any]) -> ValidationException:
    items = [str(i) for i in issues]
    return ValidationException(
        detail=f'invalid document: {items[0] if items else ""}', extra={'issues': items}
    )


def _title(value: str | None) -> str:
    return text_field(value, 'title', 200) or 'Untitled'


# --- addresses (Blog-0106…0109) -------------------------------------------------------------------------


async def _title_slug(session: DBAsyncScopedSession, blog: Blog, post: BlogPost) -> str:
    """A free slug of the post's title (``post`` without Latin letters), its own slug counting as free."""
    return await free_slug(
        session,
        BlogPost,
        blog.id,
        slugify(post.title, 80) or 'post',
        exclude=post.id,
        reserved=RESERVED_POST_SLUGS,
    )


async def _follow_title(
    session: DBAsyncScopedSession, blog: Blog, post: BlogPost
) -> None:
    """Blog-0107: a post never published whose slug was not edited by hand follows its title."""
    if post.slug_auto and post.published_at is None:
        post.slug = await _title_slug(session, blog, post)


async def _set_title(
    session: DBAsyncScopedSession, blog: Blog, post: BlogPost, value: str | None
) -> bool:
    """New title (+ the slug that follows it); ``True`` when it changed."""
    title = _title(value)
    if title == post.title:
        return False
    post.title = title
    await _follow_title(session, blog, post)
    return True


async def change_slug(
    session: DBAsyncScopedSession, blog: Blog, post: BlogPost, wanted: str
) -> bool:
    """``PATCH slug``: a value → that slug (400 invalid / reserved, 409 ``slug_taken``), ``slug_auto`` off; ``""``
    → regenerated from the title, ``slug_auto`` back on while never published. A value equal to the current slug
    changes nothing. After the first publication the old slug goes to ``former_slugs`` (Blog-0108). Returns
    ``True`` when the address changed."""
    old = post.slug
    if wanted:
        if wanted == old:
            return False
        post.slug = await pick_slug(
            session,
            BlogPost,
            blog.id,
            wanted,
            post.title,
            default='post',
            exclude=post.id,
            check=post_slug_error,
        )
        post.slug_auto = False
    else:
        post.slug = await _title_slug(session, blog, post)
        post.slug_auto = post.published_at is None
    if post.slug == old:
        return False
    if post.published_at is not None:
        post.former_slugs = remember_slug(post.former_slugs or [], old, post.slug)
    return True


# --- references: category, tags, authors --------------------------------------------------------------


async def _category_id(
    session: DBAsyncScopedSession, blog: Blog, value: object
) -> UUID | None:
    if value in (None, ''):
        return None
    cid = parse_uuid(value, 'category_id', not_found=False)
    if (
        await session.scalar(
            select(BlogCategory.id).where(
                BlogCategory.id == cid, BlogCategory.blog_id == blog.id
            )
        )
        is None
    ):
        raise ClientException(detail='category not found in this blog')
    return cid


async def _ids_in_blog(
    session: DBAsyncScopedSession,
    model: Any,
    blog: Blog,
    values: list[str],
    what: str,
    limit: int,
) -> list[UUID]:
    """Ordered, de-duplicated ids of ``model`` rows of the blog (400 for unknown ones)."""
    ids: list[UUID] = []
    for value in values:
        vid = parse_uuid(value, what, not_found=False)
        if vid not in ids:
            ids.append(vid)
    if len(ids) > limit:
        raise ClientException(detail=f'a post has at most {limit} {what}s')
    if ids:
        found = set(
            await session.scalars(
                select(model.id).where(model.id.in_(ids), model.blog_id == blog.id)
            )
        )
        if missing := [i for i in ids if i not in found]:
            raise ClientException(detail=f'{what} {missing[0]} not found in this blog')
    return ids


async def _set_tags(
    session: DBAsyncScopedSession, post: BlogPost, tag_ids: list[UUID]
) -> None:
    await session.execute(delete(BlogPostTag).where(BlogPostTag.post_id == post.id))
    session.add_all(
        BlogPostTag(tenant_id=post.tenant_id, post_id=post.id, tag_id=t)
        for t in tag_ids
    )


async def _set_authors(
    session: DBAsyncScopedSession, post: BlogPost, author_ids: list[UUID]
) -> None:
    await session.execute(
        delete(BlogPostAuthor).where(BlogPostAuthor.post_id == post.id)
    )
    session.add_all(
        BlogPostAuthor(
            tenant_id=post.tenant_id, post_id=post.id, author_id=a, position=i
        )
        for i, a in enumerate(author_ids)
    )


async def ensure_user_author(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog
) -> BlogAuthor:
    """The caller's author profile in the blog, created on first use (name from the session)."""
    author = await session.scalar(
        select(BlogAuthor).where(
            BlogAuthor.blog_id == blog.id, BlogAuthor.user_id == scope.user_id
        )
    )
    if author is not None:
        return author
    name = (scope.name or (scope.email or '').split('@')[0] or 'Author').strip()[:120]
    author = BlogAuthor(
        id=uuid.uuid7(),
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        slug=await free_slug(
            session, BlogAuthor, blog.id, slugify(name, 80) or 'author'
        ),
        display_name=name,
        links=[],
        user_id=scope.user_id,
    )
    session.add(author)
    await session.flush()
    return author


async def _post_refs(
    session: DBAsyncScopedSession, posts: list[BlogPost]
) -> tuple[
    dict[UUID, BlogTermRef],
    dict[UUID, list[BlogTermRef]],
    dict[UUID, list[BlogAuthorRef]],
]:
    """Category of each post (by category id), tags and authors (ordered) by post id."""
    ids = [p.id for p in posts]
    category_ids = {p.category_id for p in posts if p.category_id}
    categories: dict[UUID, BlogTermRef] = {}
    if category_ids:
        for c in await session.scalars(
            select(BlogCategory).where(BlogCategory.id.in_(category_ids))
        ):
            categories[c.id] = BlogTermRef(id=str(c.id), slug=c.slug, name=c.name)
    tags: dict[UUID, list[BlogTermRef]] = {}
    authors: dict[UUID, list[BlogAuthorRef]] = {}
    if ids:
        rows = await session.execute(
            select(BlogPostTag.post_id, BlogTag)
            .join(BlogTag, BlogTag.id == BlogPostTag.tag_id)
            .where(BlogPostTag.post_id.in_(ids))
            .order_by(func.lower(BlogTag.name))
        )
        for post_id, tag in rows.all():
            tags.setdefault(post_id, []).append(
                BlogTermRef(id=str(tag.id), slug=tag.slug, name=tag.name)
            )
        rows = await session.execute(
            select(BlogPostAuthor.post_id, BlogAuthor)
            .join(BlogAuthor, BlogAuthor.id == BlogPostAuthor.author_id)
            .where(BlogPostAuthor.post_id.in_(ids))
            .order_by(BlogPostAuthor.position)
        )
        for post_id, a in rows.all():
            authors.setdefault(post_id, []).append(
                BlogAuthorRef(
                    id=str(a.id),
                    slug=a.slug,
                    display_name=a.display_name,
                    avatar_asset_id=str(a.avatar_asset_id)
                    if a.avatar_asset_id
                    else None,
                    user_id=str(a.user_id) if a.user_id else None,
                )
            )
    return categories, tags, authors


async def snapshot_meta(
    session: DBAsyncScopedSession, post: BlogPost
) -> dict[str, Any]:
    """Metadata stored with a revision (the live snapshot of a published one)."""
    tag_ids = await session.scalars(
        select(BlogPostTag.tag_id).where(BlogPostTag.post_id == post.id)
    )
    author_ids = await session.scalars(
        select(BlogPostAuthor.author_id)
        .where(BlogPostAuthor.post_id == post.id)
        .order_by(BlogPostAuthor.position)
    )
    return {
        'slug': post.slug,
        'subtitle': post.subtitle,
        'excerpt': post.excerpt,
        'cover_asset_id': str(post.cover_asset_id) if post.cover_asset_id else None,
        'cover_alt': post.cover_alt,
        'category_id': str(post.category_id) if post.category_id else None,
        'tag_ids': [str(t) for t in tag_ids],
        'author_ids': [str(a) for a in author_ids],
        'featured': post.featured,
        'seo': dict(post.seo or {}),
        'noindex': post.noindex,
    }


async def _record_usages(
    session: DBAsyncScopedSession, blog: Blog, post: BlogPost, doc: dict[str, Any]
) -> None:
    """Media used by the post (body, cover, social image) for the library's "used in" list."""
    extra = [
        f'asset:{post.cover_asset_id}' if post.cover_asset_id else None,
        (post.seo or {}).get('og_image'),
    ]
    await record_usages(
        session,
        blog.tenant_id,
        app='blog',
        ref_type='post',
        ref_id=post.id,
        label=f'{blog.name} › {post.title}',
        asset_ids=asset_ids(doc, *extra),
    )


# --- output -------------------------------------------------------------------------------------------


def lock_holder(post: BlogPost) -> UUID | None:
    if post.locked_by and post.lock_expires_at and post.lock_expires_at > utcnow():
        return post.locked_by
    return None


def _post_fields(
    post: BlogPost,
    *,
    blog: Blog,
    base_url: str,
    category: BlogTermRef | None,
    tags: list[BlogTermRef],
    authors: list[BlogAuthorRef],
    can_edit_post: bool,
    names: dict[UUID, str],
) -> dict[str, Any]:
    holder = lock_holder(post)
    return {
        'id': str(post.id),
        'blog_id': str(post.blog_id),
        'slug': post.slug,
        'slug_auto': post.slug_auto,
        'former_slugs': list(post.former_slugs or []),
        'public_url': f'{base_url}{post.slug}',
        'live': is_live(blog, post),
        'title': post.title,
        'subtitle': post.subtitle,
        'excerpt': post.excerpt,
        'status': post.status,
        'has_changes': post.published_revision_id is not None
        and post.draft_revision_id != post.published_revision_id,
        'cover_asset_id': str(post.cover_asset_id) if post.cover_asset_id else None,
        'cover_alt': post.cover_alt,
        'category': category,
        'tags': tags,
        'authors': authors,
        'featured': post.featured,
        'word_count': post.word_count,
        'reading_minutes': post.reading_minutes,
        'published_at': post.published_at,
        'scheduled_at': post.scheduled_at,
        'schedule_timezone': post.schedule_timezone,
        'review_comment': post.review_comment,
        'reviewed_at': post.reviewed_at,
        'submitted_at': post.submitted_at,
        'draft_revision_id': str(post.draft_revision_id)
        if post.draft_revision_id
        else None,
        'published_revision_id': str(post.published_revision_id)
        if post.published_revision_id
        else None,
        'locked_by': str(holder) if holder else None,
        'locked_by_name': names.get(holder) if holder else None,
        'lock_expires_at': post.lock_expires_at if holder else None,
        'can_edit': can_edit_post,
        'created_by': str(post.created_by) if post.created_by else None,
        'updated_by': str(post.updated_by) if post.updated_by else None,
        'created_at': post.created_at,
        'updated_at': post.updated_at,
    }


async def post_outs(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    posts: list[BlogPost],
    permissions: set[str],
) -> list[BlogPostOut]:
    categories, tags, authors = await _post_refs(session, posts)
    names = await user_names(session, [lock_holder(p) for p in posts])
    base_url = blog_url(scope.organization.slug, blog.slug)
    out: list[BlogPostOut] = []
    for p in posts:
        refs = authors.get(p.id, [])
        own = is_own(
            scope.user_id, p.created_by, (UUID(a.user_id) for a in refs if a.user_id)
        )
        out.append(
            BlogPostOut(
                **_post_fields(
                    p,
                    blog=blog,
                    base_url=base_url,
                    category=categories.get(p.category_id) if p.category_id else None,
                    tags=tags.get(p.id, []),
                    authors=refs,
                    can_edit_post=can_edit(permissions, own),
                    names=names,
                )
            )
        )
    return out


async def draft_revision(
    session: DBAsyncScopedSession, post: BlogPost
) -> BlogPostRevision | None:
    if post.draft_revision_id is None:
        return None
    return await session.get(BlogPostRevision, post.draft_revision_id)


async def post_detail(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPostDetailOut:
    permissions = await BLOG.permissions(scope, blog.id)
    (base,) = await post_outs(session, scope, blog, [post], permissions)
    revision = await draft_revision(session, post)
    return BlogPostDetailOut(
        **{f: getattr(base, f) for f in base.__struct_fields__},
        seo=dict(post.seo or {}),
        noindex=post.noindex,
        doc=migrate_document(revision.doc) if revision else empty_document(),
        revision_created_at=revision.created_at if revision else None,
        revision_source=revision.source if revision else None,
        permissions=sorted(permissions),
    )


# --- list ---------------------------------------------------------------------------------------------


def _like(q: str) -> str:
    escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


async def list_posts(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    *,
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
    """Posts of the blog with the quick-tab counts (Blog §6): ``status`` ``all`` / none = every status but
    ``archived``; ``counts`` apply the other filters."""
    if status not in (None, '', 'all', *POST_STATUSES):
        raise ClientException(
            detail=f'status must be all or one of {", ".join(POST_STATUSES)}'
        )
    if sort not in _SORTS:
        raise ClientException(detail=f'sort must be one of {", ".join(_SORTS)}')
    conds: list[Any] = [BlogPost.blog_id == blog.id, BlogPost.deleted_at.is_(None)]
    if category_id:
        conds.append(
            BlogPost.category_id
            == parse_uuid(category_id, 'category_id', not_found=False)
        )
    if tag_id:
        tid = parse_uuid(tag_id, 'tag_id', not_found=False)
        conds.append(
            BlogPost.id.in_(
                select(BlogPostTag.post_id).where(BlogPostTag.tag_id == tid)
            )
        )
    if author_id:
        aid = parse_uuid(author_id, 'author_id', not_found=False)
        conds.append(
            BlogPost.id.in_(
                select(BlogPostAuthor.post_id).where(BlogPostAuthor.author_id == aid)
            )
        )
    if featured is not None:
        conds.append(BlogPost.featured.is_(featured))
    if q and q.strip():
        like = _like(q)
        conds.append(
            or_(
                BlogPost.title.ilike(like, escape='\\'),
                BlogPost.subtitle.ilike(like, escape='\\'),
                BlogPost.excerpt.ilike(like, escape='\\'),
                BlogPost.slug.ilike(like, escape='\\'),
            )
        )
    rows = await session.execute(
        select(BlogPost.status, func.count()).where(*conds).group_by(BlogPost.status)
    )
    counts = dict.fromkeys(POST_STATUSES, 0) | dict(rows.tuples().all())
    counts['all'] = sum(n for s, n in counts.items() if s != 'archived')
    if status in (None, '', 'all'):
        conds.append(BlogPost.status != 'archived')
        total = counts['all']
    else:
        conds.append(BlogPost.status == status)
        total = counts[status]
    column, default_order = _SORTS[sort]
    direction = order if order in ('asc', 'desc') else default_order
    ordering = (
        column.desc().nulls_last() if direction == 'desc' else column.asc().nulls_last()
    )
    posts = list(
        await session.scalars(
            select(BlogPost)
            .where(*conds)
            .order_by(ordering, BlogPost.id.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
    )
    permissions = await BLOG.permissions(scope, blog.id)
    return BlogPostListOut(
        items=await post_outs(session, scope, blog, posts, permissions),
        total=total,
        counts=counts,
    )


# --- create / update / delete ----------------------------------------------------------------------------


async def _new_revision(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    post: BlogPost,
    doc: dict[str, Any],
    *,
    source: str,
    note: str | None = None,
) -> BlogPostRevision:
    revision = BlogPostRevision(
        id=uuid.uuid7(),
        tenant_id=post.tenant_id,
        blog_id=post.blog_id,
        post_id=post.id,
        doc=doc,
        source=source,
        title=post.title,
        meta=await snapshot_meta(session, post),
        note=(note or None) and note[:500],
        created_by=scope.user_id if scope else None,
        created_at=utcnow(),
    )
    session.add(revision)
    post.draft_revision_id = revision.id
    return revision


async def create_post(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, data: BlogPostCreate
) -> BlogPost:
    """A new draft (Blog-0100): byline = ``author_ids`` or the caller's author profile."""
    title = _title(data.title)
    doc = data.doc if data.doc is not None else empty_document()
    if issues := validate_document(doc):
        raise invalid_document(issues)
    category_id = await _category_id(session, blog, data.category_id)
    tag_ids = await _ids_in_blog(
        session, BlogTag, blog, data.tag_ids or [], 'tag', MAX_TAGS
    )
    author_ids = await _ids_in_blog(
        session, BlogAuthor, blog, data.author_ids or [], 'author', MAX_AUTHORS
    )
    if not author_ids:
        author_ids = [(await ensure_user_author(session, scope, blog)).id]
    words, minutes = reading_time(doc)
    post = BlogPost(
        id=uuid.uuid7(),
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        slug=await pick_slug(
            session,
            BlogPost,
            blog.id,
            data.slug,
            title,
            default='post',
            check=post_slug_error,
            reserved=RESERVED_POST_SLUGS,
        ),
        slug_auto=not data.slug,
        former_slugs=[],
        title=title,
        status='draft',
        category_id=category_id,
        featured=data.featured,
        seo={},
        word_count=words,
        reading_minutes=minutes,
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(post)
    await session.flush()
    await _set_tags(session, post, tag_ids)
    await _set_authors(session, post, author_ids)
    await session.flush()
    await _new_revision(session, scope, post, doc, source=data.source)
    await _record_usages(session, blog, post, doc)
    blog.updated_at = utcnow()
    await session.flush()
    return post


async def _working_draft(
    session: DBAsyncScopedSession, scope: RequestScope, post: BlogPost
) -> BlogPostRevision:
    """The draft revision to change in place; a published one is copied into a new draft first."""
    draft = await draft_revision(session, post)
    if draft is None or draft.id == post.published_revision_id:
        doc = copy.deepcopy(draft.doc) if draft else empty_document()
        draft = await _new_revision(
            session, scope, post, doc, source=draft.source if draft else 'visual'
        )
    return draft


async def update_post(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    data: BlogPostUpdate,
) -> BlogPost:
    """Metadata (Blog-0104 / 0300); on a published post the change waits in a new draft revision — except the
    slug, public at once (a new release when the post is live, Blog-0108)."""
    changed = False
    if data.title is not None:
        changed = await _set_title(session, blog, post, data.title)
    moved = (
        await change_slug(session, blog, post, data.slug)
        if data.slug is not None
        else False
    )
    if data.subtitle is not msgspec.UNSET:
        post.subtitle, changed = text_field(data.subtitle, 'subtitle', 300), True  # type: ignore[arg-type]
    if data.excerpt is not msgspec.UNSET:
        post.excerpt, changed = text_field(data.excerpt, 'excerpt', 1000), True  # type: ignore[arg-type]
    if data.cover_asset_id is not msgspec.UNSET:
        post.cover_asset_id = (
            await check_asset(session, scope, data.cover_asset_id, 'cover_asset_id')
            if data.cover_asset_id
            else None
        )
        changed = True
    if data.cover_alt is not msgspec.UNSET:
        post.cover_alt, changed = text_field(data.cover_alt, 'cover_alt', 500), True  # type: ignore[arg-type]
    if data.category_id is not msgspec.UNSET:
        post.category_id, changed = (
            await _category_id(session, blog, data.category_id),
            True,
        )
    if data.tag_ids is not None:
        await _set_tags(
            session,
            post,
            await _ids_in_blog(session, BlogTag, blog, data.tag_ids, 'tag', MAX_TAGS),
        )
        changed = True
    if data.author_ids is not None:
        ids = await _ids_in_blog(
            session, BlogAuthor, blog, data.author_ids, 'author', MAX_AUTHORS
        )
        await _set_authors(session, post, ids)
        changed = True
    if data.featured is not None:
        post.featured, changed = data.featured, True
    if data.seo is not None:
        seo = clean_seo(data.seo)
        if seo.get('og_image'):
            await check_asset(session, scope, seo['og_image'], 'seo.og_image')
        post.seo, changed = seo, True
    if data.noindex is not None:
        post.noindex, changed = data.noindex, True
    if not changed and not moved:
        return post
    await session.flush()
    if changed:
        draft = await _working_draft(session, scope, post)
    else:  # only the address: no pending change of the live version
        draft = await draft_revision(session, post)
        if draft is not None and draft.id == post.published_revision_id:
            draft = None
    if draft is not None:
        draft.title, draft.meta = post.title, await snapshot_meta(session, post)
        await _record_usages(session, blog, post, draft.doc)
    post.updated_by, post.updated_at = scope.user_id, utcnow()
    await session.flush()
    if moved and is_live(blog, post):
        await rebuild_release(session, blog)
    return post


async def delete_post(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> None:
    """Soft delete: gone from the blog and the editor; once published, its addresses answer 410 (``gone``)."""
    now = utcnow()
    post.deleted_at, post.locked_by, post.lock_expires_at = now, None, None
    post.updated_by, post.updated_at = scope.user_id, now
    await record_usages(
        session,
        blog.tenant_id,
        app='blog',
        ref_type='post',
        ref_id=post.id,
        label=None,
        asset_ids=[],
    )
    await session.flush()
    if post.published_at is not None:
        await rebuild_release(session, blog)
    logger.info(
        'blog.post.deleted',
        extra={'post_id': str(post.id), 'actor': str(scope.user_id)},
    )


# --- drafts / revisions / locks ---------------------------------------------------------------------------


async def save_draft(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    data: BlogDraftSave,
    *,
    source: str | None = None,
) -> tuple[BlogPostRevision, bool]:
    """Autosave title + body (Blog-0101); returns the revision and whether it is a new one. 409 ``locked``
    while another user holds the lock, 409 ``stale_draft`` when another user saved after ``base_revision_id``."""
    if issues := validate_document(data.doc):
        raise invalid_document(issues)
    holder = lock_holder(post)
    if holder and holder != scope.user_id:
        names = await user_names(session, [holder])
        raise ConflictException(
            detail=f'{names.get(holder, "Someone")} is editing this post',
            extra={'code': 'locked'},
        )
    current = await draft_revision(session, post)
    if (
        data.base_revision_id
        and current is not None
        and str(current.id) != data.base_revision_id
        and current.created_by != scope.user_id
    ):
        raise ConflictException(
            detail='the post was changed by someone else: reload it',
            extra={'code': 'stale_draft'},
        )
    if data.title is not None:
        await _set_title(session, blog, post, data.title)
    source = source or data.source
    now = utcnow()
    reuse = (
        current is not None
        and current.id != post.published_revision_id
        and current.created_by == scope.user_id
        and current.source == source
        and current.created_at > now - REVISION_WINDOW
        and not data.note
    )
    if reuse:
        assert current is not None
        current.doc, current.title, current.meta = (
            data.doc,
            post.title,
            await snapshot_meta(session, post),
        )
        revision, created = current, False
    else:
        revision = await _new_revision(
            session, scope, post, data.doc, source=source, note=data.note
        )
        created = True
    post.word_count, post.reading_minutes = reading_time(data.doc)
    if holder == scope.user_id:
        post.lock_expires_at = now + LOCK_TTL
    post.updated_by, post.updated_at = scope.user_id, now
    await _record_usages(session, blog, post, data.doc)
    await session.flush()
    return revision, created


def _revision_out(
    r: BlogPostRevision, post: BlogPost, names: dict[UUID, str]
) -> dict[str, Any]:
    return {
        'id': str(r.id),
        'source': r.source,
        'title': r.title,
        'created_by': str(r.created_by) if r.created_by else None,
        'created_by_name': names.get(r.created_by) if r.created_by else None,
        'note': r.note,
        'created_at': r.created_at,
        'is_draft': r.id == post.draft_revision_id,
        'is_published': r.id == post.published_revision_id,
    }


async def list_revisions(
    session: DBAsyncScopedSession, post: BlogPost, limit: int = 50
) -> list[BlogRevisionOut]:
    rows = list(
        await session.scalars(
            select(BlogPostRevision)
            .where(BlogPostRevision.post_id == post.id)
            .order_by(BlogPostRevision.created_at.desc(), BlogPostRevision.id.desc())
            .limit(max(1, min(limit, 200)))
        )
    )
    names = await user_names(session, [r.created_by for r in rows])
    return [BlogRevisionOut(**_revision_out(r, post, names)) for r in rows]


async def _revision(
    session: DBAsyncScopedSession, post: BlogPost, revision_id: object
) -> BlogPostRevision:
    rid = parse_uuid(revision_id, 'revision')
    revision = await session.scalar(
        select(BlogPostRevision).where(
            BlogPostRevision.id == rid, BlogPostRevision.post_id == post.id
        )
    )
    if revision is None:
        raise NotFoundException(detail='revision not found')
    return revision


async def get_revision(
    session: DBAsyncScopedSession, post: BlogPost, revision_id: object
) -> BlogRevisionDetailOut:
    r = await _revision(session, post, revision_id)
    names = await user_names(session, [r.created_by])
    return BlogRevisionDetailOut(
        **_revision_out(r, post, names), doc=migrate_document(r.doc), meta=r.meta or {}
    )


async def restore_revision(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    revision_id: object,
) -> BlogPostRevision:
    """Copy a revision's title + body into a new draft revision (metadata stays as it is)."""
    source = await _revision(session, post, revision_id)
    data = BlogDraftSave(
        doc=copy.deepcopy(migrate_document(source.doc)),
        title=source.title,
        note=f'Restored from {source.created_at:%Y-%m-%d %H:%M}',
    )
    revision, _ = await save_draft(session, scope, blog, post, data, source='restore')
    return revision


async def lock_post(
    session: DBAsyncScopedSession, scope: RequestScope, post: BlogPost, *, force: bool
) -> tuple[bool, UUID | None]:
    """Soft lock (Blog-0101): one editor at a time for ``LOCK_TTL``; ``force`` takes it over."""
    holder = lock_holder(post)
    if holder and holder != scope.user_id and not force:
        return False, holder
    post.locked_by, post.lock_expires_at = scope.user_id, utcnow() + LOCK_TTL
    await session.flush()
    return True, scope.user_id


async def unlock_post(
    session: DBAsyncScopedSession, scope: RequestScope, post: BlogPost
) -> None:
    if post.locked_by == scope.user_id:
        post.locked_by, post.lock_expires_at = None, None
        await session.flush()
