"""Public releases of a blog (taas-specs/blog/blog-publishing-spec.md §3 / §5).

The site renderer reads a blog through immutable snapshots, like sites: a **release** (``taas_blog_releases``) is
the index of the blog — published posts (metadata of their published revision), ``gone`` slugs, categories,
tags, authors and the media of covers / avatars / social images with their CDN URLs. Bodies are the published
revisions themselves (``assets`` + ``cdn_origin`` stored at publish time, ``publish_revision_media``).

``rebuild_release(session, blog)`` is called after every change of the public output (post publish / update /
unpublish / archive / delete, ``publish_due``, slug change of a live post, blog update, taxonomy / author
changes): a new release only when the content differs from the live one; the last ``KEEP_RELEASES`` are kept.
Media go to the public scope ``blog/<blogId>`` (``ews.media._publishing``), removed with the blog (delete /
archive) and copied again on restore.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from db.models.blog import (
    Blog,
    BlogAuthor,
    BlogCategory,
    BlogPost,
    BlogPostRevision,
    BlogRelease,
    BlogTag,
)
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import delete, func, select, text

from ews.media._publishing import asset_map, publish_assets, remove_public_scope
from ews.shared import utcnow
from ews.sites._document import asset_ids, migrate_document
from ews.sites._settings import sites_settings
from ews.sites.schemas import RouteOut

from ._rules import (
    SNAPSHOT_SCHEMA,
    content_digest,
    public_settings,
    public_slugs,
    snapshot_asset_refs,
    snapshot_post,
)

logger = logging.getLogger(__name__)

KEEP_RELEASES = 20
"""Releases kept per blog (the renderer caches the ones it served)."""


def blog_scope(blog_id: UUID | str) -> str:
    """Public CDN scope of a blog's media: ``{tenantId}/blog/{blogId}/{sha256}.{ext}``."""
    return f'blog/{blog_id}'


def blog_url(org_slug: str, blog_slug: str) -> str:
    """Public address of a blog home: ``<scheme>://<org>.<SITES_DOMAIN>[:port]/<blog-slug>/`` (Blog-0110)."""
    return sites_settings().public_url(org_slug, f'/{blog_slug}/')


def is_live(blog: Blog, post: BlogPost) -> bool:
    """The post is readable on the public blog now."""
    return (
        post.published_revision_id is not None
        and post.deleted_at is None
        and blog.status == 'active'
        and blog.deleted_at is None
    )


# --- media ------------------------------------------------------------------------------------------


async def publish_revision_media(
    session: DBAsyncScopedSession,
    blog: Blog,
    revision: BlogPostRevision,
    doc: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    """Copy the media of a body going live (+ its cover) to the blog's public scope and store them on the
    revision (``assets``, ``cdn_origin``). 503 before anything changes when the CDN copy fails."""
    cover = meta.get('cover_asset_id')
    refs = asset_ids(doc, f'asset:{cover}' if cover else None)
    assets = await asset_map(session, blog.tenant_id, refs)
    revision.assets, revision.cdn_origin = await publish_assets(
        session, blog.tenant_id, blog_scope(blog.id), assets
    )


async def remove_blog_media(blog: Blog) -> None:
    """Delete / archive: drop every public copy of the blog (best effort)."""
    await remove_public_scope(blog.tenant_id, blog_scope(blog.id))


async def republish_media(session: DBAsyncScopedSession, blog: Blog) -> None:
    """Restore of an archived blog: copy the media of the live bodies again (removed on archive)."""
    rows = await session.execute(
        select(BlogPostRevision)
        .join(BlogPost, BlogPost.published_revision_id == BlogPostRevision.id)
        .where(BlogPost.blog_id == blog.id, BlogPost.deleted_at.is_(None))
    )
    for revision in rows.scalars():
        await publish_revision_media(
            session, blog, revision, migrate_document(revision.doc), revision.meta or {}
        )


# --- snapshot ---------------------------------------------------------------------------------------


async def build_snapshot(session: DBAsyncScopedSession, blog: Blog) -> dict[str, Any]:
    """The renderer's view of the blog (blog-publishing-spec §5) without its header (release id, version,
    generated at). Only published posts, newest first; only the categories / tags / authors they use."""
    org = (
        await session.execute(
            text('select slug, name from taas_organizations where id = :id'),
            {'id': blog.organization_id},
        )
    ).first()
    org_slug, org_name = (org.slug, org.name) if org else ('', '')
    rows = (
        await session.execute(
            select(BlogPost, BlogPostRevision)
            .join(
                BlogPostRevision, BlogPostRevision.id == BlogPost.published_revision_id
            )
            .where(BlogPost.blog_id == blog.id, BlogPost.deleted_at.is_(None))
            .order_by(BlogPost.published_at.desc().nulls_last(), BlogPost.id.desc())
        )
    ).all()
    deleted = (
        await session.execute(
            select(BlogPost.slug, BlogPost.former_slugs).where(
                BlogPost.blog_id == blog.id,
                BlogPost.deleted_at.is_not(None),
                BlogPost.published_at.is_not(None),
            )
        )
    ).all()
    formers, gone = public_slugs(
        ((p.slug, p.former_slugs or []) for p, _ in rows),
        ([slug, *(former or [])] for slug, former in deleted),
    )
    used_categories = {(r.meta or {}).get('category_id') for _, r in rows}
    used_tags = {t for _, r in rows for t in (r.meta or {}).get('tag_ids') or []}
    used_authors = {a for _, r in rows for a in (r.meta or {}).get('author_ids') or []}
    categories = [
        c
        for c in await session.scalars(
            select(BlogCategory)
            .where(BlogCategory.blog_id == blog.id)
            .order_by(BlogCategory.position, BlogCategory.created_at)
        )
        if str(c.id) in used_categories
    ]
    tags = [
        t
        for t in await session.scalars(
            select(BlogTag)
            .where(BlogTag.blog_id == blog.id)
            .order_by(func.lower(BlogTag.name))
        )
        if str(t.id) in used_tags
    ]
    authors = [
        a
        for a in await session.scalars(
            select(BlogAuthor)
            .where(BlogAuthor.blog_id == blog.id)
            .order_by(func.lower(BlogAuthor.display_name), BlogAuthor.id)
        )
        if str(a.id) in used_authors
    ]
    posts = [
        snapshot_post(
            post,
            revision,
            former,
            categories={str(c.id) for c in categories},
            tags={str(t.id) for t in tags},
            authors={str(a.id) for a in authors},
        )
        for (post, revision), former in zip(rows, formers, strict=True)
    ]
    author_entries = [
        {
            'id': str(a.id),
            'slug': a.slug,
            'name': a.display_name,
            'bio': a.bio,
            'avatar': f'asset:{a.avatar_asset_id}' if a.avatar_asset_id else None,
            'links': list(a.links or []),
        }
        for a in authors
    ]
    assets = await asset_map(
        session, blog.tenant_id, snapshot_asset_refs(posts, author_entries)
    )
    assets, cdn_origin = await publish_assets(
        session, blog.tenant_id, blog_scope(blog.id), assets
    )
    return {
        'schema': SNAPSHOT_SCHEMA,
        'kind': 'blog',
        'blog': {
            'id': str(blog.id),
            'slug': blog.slug,
            'name': blog.name,
            'description': blog.description,
            'locale': blog.locale,
            'settings': public_settings(blog.settings or {}),
        },
        'organization': {'slug': org_slug, 'name': org_name},
        'base_url': blog_url(org_slug, blog.slug),
        'cdn_origin': cdn_origin,
        'posts': posts,
        'gone': gone,
        'categories': [
            {
                'id': str(c.id),
                'slug': c.slug,
                'name': c.name,
                'description': c.description,
            }
            for c in categories
        ],
        'tags': [{'id': str(t.id), 'slug': t.slug, 'name': t.name} for t in tags],
        'authors': author_entries,
        'assets': assets,
    }


async def rebuild_release(
    session: DBAsyncScopedSession, blog: Blog
) -> BlogRelease | None:
    """Build the blog's release after a change of its public output; ``None`` for a deleted / archived blog.

    The blog row is locked (one rebuild at a time per blog). When the content equals the live release, nothing
    is written. Otherwise a new release (``version`` + 1) becomes live and releases older than the last
    ``KEEP_RELEASES`` are deleted.
    """
    await session.flush()
    await session.refresh(
        blog, ['live_release_id', 'status', 'deleted_at'], with_for_update=True
    )
    if blog.deleted_at is not None or blog.status != 'active':
        return None
    content = await build_snapshot(session, blog)
    live = (
        await session.get(BlogRelease, blog.live_release_id)
        if blog.live_release_id
        else None
    )
    if live is not None and content_digest(live.snapshot) == content_digest(content):
        return live
    version = (
        await session.scalar(
            select(func.max(BlogRelease.version)).where(BlogRelease.blog_id == blog.id)
        )
        or 0
    ) + 1
    now = utcnow()
    release_id = uuid.uuid7()
    release = BlogRelease(
        id=release_id,
        tenant_id=blog.tenant_id,
        blog_id=blog.id,
        version=version,
        snapshot={
            'schema': content.pop('schema'),
            'kind': content.pop('kind'),
            'release_id': str(release_id),
            'version': version,
            'generated_at': now.isoformat(),
            **content,
        },
        created_at=now,
    )
    session.add(release)
    blog.live_release_id = release.id
    await session.flush()
    await session.execute(
        delete(BlogRelease).where(
            BlogRelease.blog_id == blog.id,
            BlogRelease.version <= version - KEEP_RELEASES,
        )
    )
    logger.info(
        'blog.released',
        extra={
            'blog_id': str(blog.id),
            'release_id': str(release.id),
            'version': version,
        },
    )
    return release


@db_context_session(auto_commit=True)
async def rebuild_missing_releases(
    *,
    tenant_id: UUID | None = None,
    session: DBAsyncScopedSession | None = None,
) -> list[UUID]:
    """Active blogs without a release (created before B3): copy the media of their live bodies and build a
    first release. Idempotent; returns the blog ids."""
    assert session is not None  # injected by db_context_session
    stmt = select(Blog).where(
        Blog.deleted_at.is_(None),
        Blog.status == 'active',
        Blog.live_release_id.is_(None),
    )
    if tenant_id is not None:
        stmt = stmt.where(Blog.tenant_id == tenant_id)
    done: list[UUID] = []
    for blog in list(await session.scalars(stmt)):
        await republish_media(session, blog)
        if await rebuild_release(session, blog) is not None:
            done.append(blog.id)
    return done


# --- internal API (renderer) ------------------------------------------------------------------------


async def blog_routes(session: DBAsyncScopedSession) -> list[RouteOut]:
    """Routes of the active blogs with a release (system address ``<org host>/<blog-slug>``) for the routing
    table of the site renderer (``ews.sites._publish.register_route_source``)."""
    settings = sites_settings()
    rows = await session.execute(
        text(
            'select b.id, b.tenant_id, b.slug, b.live_release_id, o.slug as org_slug '
            'from taas_blog_blogs b join taas_organizations o on o.id = b.organization_id '
            "where b.deleted_at is null and b.status = 'active' and b.mount = 'system' "
            'and b.live_release_id is not null '
            'order by o.slug, b.slug'
        )
    )
    return [
        RouteOut(
            host=settings.org_host(r.org_slug),
            prefix=f'/{r.slug}',
            kind='blog',
            blog_id=str(r.id),
            tenant_id=str(r.tenant_id),
            release_id=str(r.live_release_id),
        )
        for r in rows
    ]


async def release_snapshot(
    session: DBAsyncScopedSession, release_id: UUID
) -> dict[str, Any] | None:
    """A release of a blog that is not deleted."""
    return await session.scalar(
        select(BlogRelease.snapshot)
        .join(Blog, Blog.id == BlogRelease.blog_id)
        .where(BlogRelease.id == release_id, Blog.deleted_at.is_(None))
    )


async def published_revision(
    session: DBAsyncScopedSession, revision_id: UUID
) -> BlogPostRevision | None:
    """A revision that went live (``assets`` set at publish, or the live one of a post published before B3) of
    a post and blog that are not deleted."""
    return await session.scalar(
        select(BlogPostRevision)
        .join(BlogPost, BlogPost.id == BlogPostRevision.post_id)
        .join(Blog, Blog.id == BlogPostRevision.blog_id)
        .where(
            BlogPostRevision.id == revision_id,
            BlogPost.deleted_at.is_(None),
            Blog.deleted_at.is_(None),
            BlogPostRevision.assets.is_not(None)
            | (BlogPost.published_revision_id == BlogPostRevision.id),
        )
    )
