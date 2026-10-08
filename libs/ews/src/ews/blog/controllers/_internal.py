"""``/api/v1/sites-internal/blog-*`` — what the site renderer reads to serve blogs (blog-publishing-spec §5).

Same guard as the sites renderer API (``X-Sites-Renderer-Key`` = ``SITES_RENDERER_KEY``, ``ews.sites.require_renderer``);
internal network only. Blog routes are added to ``GET /api/v1/sites-internal/routes`` through
``ews.sites.register_route_source`` (``ews.blog.get_blog_controllers``).
"""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from foundation.http import BaseController, get
from foundation.http.context import Context

from ews.shared import parse_uuid
from ews.sites import require_renderer
from ews.sites._document import migrate_document

from .. import _release as rel
from ..schemas import BlogPublishedBodyOut, BlogReleaseSnapshotOut


class BlogInternalController(BaseController):
    api_prefix = '/api/v1/sites-internal'
    tags = ('Blog (renderer)',)

    @get(
        '/blog-releases/{release_id}',
        summary='Blog release snapshot: index, posts, taxonomy, authors, media (immutable: cache forever)',
    )
    @db_context_session
    async def release(
        self, release_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> BlogReleaseSnapshotOut:
        require_renderer(ctx)
        rid = parse_uuid(release_id, 'release')
        snapshot = await rel.release_snapshot(session, rid)
        if snapshot is None:
            raise NotFoundException(detail='release not found')
        return BlogReleaseSnapshotOut(release_id=str(rid), snapshot=snapshot)

    @get(
        '/blog-posts/{revision_id}',
        summary='Body of a published post revision with its media (404 unless it was published)',
    )
    @db_context_session
    async def post_body(
        self, revision_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> BlogPublishedBodyOut:
        require_renderer(ctx)
        revision = await rel.published_revision(
            session, parse_uuid(revision_id, 'revision')
        )
        if revision is None:
            raise NotFoundException(detail='published revision not found')
        return BlogPublishedBodyOut(
            revision_id=str(revision.id),
            doc=migrate_document(revision.doc),
            assets=revision.assets or {},
            cdn_origin=revision.cdn_origin,
        )
