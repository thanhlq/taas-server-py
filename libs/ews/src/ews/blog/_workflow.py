"""Editorial workflow (Blog-0102 / 0103): an author submits, an editor requests changes or approves (publish now or
schedule), publishes / updates, unpublishes, archives. Status machine: ``_rules.transition`` (409
``invalid_transition``).

Publishing makes the current draft revision live (``published_revision_id``) with a snapshot of the metadata
(+ reading time, ``live_at``) and copies its media to the public CDN (``assets``, ``cdn_origin`` on the revision);
``published_at`` keeps the first publication. Every change of what is live rebuilds the blog's release
(``_release.rebuild_release``). ``publish_due`` publishes the scheduled posts whose time has come (idempotent,
row-locked) — called by the scheduler worker (🚧 not wired yet).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from db.models.blog import Blog, BlogPost
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, ServiceUnavailableException
from sqlalchemy import select

from ews.security import RequestScope
from ews.shared import ConflictException, utcnow
from ews.sites._document import migrate_document, validate_document

from ._posts import draft_revision, invalid_document, snapshot_meta
from ._release import publish_revision_media, rebuild_release
from ._rules import InvalidTransition, reading_time, schedule_instant, transition
from ._service import logger, text_field


def _next(post: BlogPost, action: str, *, scheduled: bool = False) -> str:
    try:
        return transition(
            action,
            post.status,
            was_published=post.published_at is not None,
            scheduled=scheduled,
        )
    except InvalidTransition as error:
        raise ConflictException(
            detail=str(error), extra={'code': 'invalid_transition'}
        ) from error


def _touch(post: BlogPost, actor: UUID | None, now: datetime) -> None:
    post.updated_at = now
    if actor is not None:
        post.updated_by = actor


async def _go_live(
    session: DBAsyncScopedSession,
    blog: Blog,
    post: BlogPost,
    actor: UUID | None,
    when: datetime,
) -> None:
    """The draft revision becomes the live one, with the current metadata (Blog §3: **Update**) and its media on
    the CDN. Nothing changes when the body is invalid (400) or the CDN copy fails (503)."""
    draft = await draft_revision(session, post)
    if draft is None:
        raise ClientException(detail='the post has no content to publish')
    doc = migrate_document(draft.doc)
    if issues := validate_document(doc):
        raise invalid_document(issues)
    words, minutes = reading_time(doc)
    meta = {
        **await snapshot_meta(session, post),
        'word_count': words,
        'reading_minutes': minutes,
        'live_at': when.isoformat(),
    }
    await publish_revision_media(session, blog, draft, doc, meta)
    draft.title, draft.meta = post.title, meta
    post.published_revision_id = draft.id
    post.slug_auto = False  # the address is public: frozen (Blog-0108)
    post.published_at = post.published_at or when
    post.published_by = actor
    post.scheduled_at = post.schedule_timezone = None
    post.review_comment = None
    post.status = 'published'


async def submit(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPost:
    """Author → **Submit for review** (``draft`` / ``unpublished`` → ``in_review``)."""
    now = utcnow()
    post.status = _next(post, 'submit')
    post.submitted_by, post.submitted_at, post.review_comment = scope.user_id, now, None
    _touch(post, scope.user_id, now)
    await session.flush()
    return post


async def request_changes(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    comment: str,
) -> BlogPost:
    """Editor → back to ``draft`` with a comment for the author."""
    text = text_field(comment, 'comment', 2000, required=True)
    now = utcnow()
    post.status = _next(post, 'request_changes')
    post.review_comment, post.reviewed_by, post.reviewed_at = text, scope.user_id, now
    _touch(post, scope.user_id, now)
    await session.flush()
    return post


async def publish(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPost:
    """Publish now, or publish the pending changes of a published post (**Update**)."""
    now = utcnow()
    was = post.status
    _next(post, 'publish')
    await _go_live(session, blog, post, scope.user_id, now)
    if was == 'in_review':
        post.reviewed_by, post.reviewed_at = scope.user_id, now
    _touch(post, scope.user_id, now)
    await session.flush()
    await rebuild_release(session, blog)
    logger.info(
        'blog.post.published',
        extra={'post_id': str(post.id), 'actor': str(scope.user_id)},
    )
    return post


async def schedule(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    scheduled_at: datetime,
    timezone: str | None,
    *,
    action: str = 'schedule',
) -> BlogPost:
    """Publish at ``scheduled_at`` (wall time in ``timezone`` when naive) — Blog-0103."""
    now = utcnow()
    instant, zone = schedule_instant(scheduled_at, timezone, now)
    post.status = _next(post, action, scheduled=True)
    post.scheduled_at, post.schedule_timezone = instant, zone
    _touch(post, scope.user_id, now)
    await session.flush()
    return post


async def approve(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    blog: Blog,
    post: BlogPost,
    scheduled_at: datetime | None,
    timezone: str | None,
) -> BlogPost:
    """Editor approves a post in review: publish now, or schedule it when ``scheduled_at`` is given."""
    if scheduled_at is None:
        _next(post, 'approve')
        return await publish(session, scope, blog, post)
    post = await schedule(
        session, scope, blog, post, scheduled_at, timezone, action='approve'
    )
    post.reviewed_by, post.reviewed_at, post.review_comment = (
        scope.user_id,
        utcnow(),
        None,
    )
    await session.flush()
    return post


async def unpublish(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPost:
    """Take a published post off the blog (→ ``unpublished``) or cancel a schedule."""
    now = utcnow()
    was_live = post.published_revision_id is not None
    post.status = _next(post, 'unpublish')
    post.published_revision_id = None
    post.scheduled_at = post.schedule_timezone = None
    _touch(post, scope.user_id, now)
    await session.flush()
    if was_live:
        await rebuild_release(session, blog)
    logger.info(
        'blog.post.unpublished',
        extra={'post_id': str(post.id), 'actor': str(scope.user_id)},
    )
    return post


async def archive(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPost:
    """Archive (off the blog, out of the default list)."""
    now = utcnow()
    was_live = post.published_revision_id is not None
    post.status = _next(post, 'archive')
    post.published_revision_id = None
    post.scheduled_at = post.schedule_timezone = None
    _touch(post, scope.user_id, now)
    await session.flush()
    if was_live:
        await rebuild_release(session, blog)
    return post


async def unarchive(
    session: DBAsyncScopedSession, scope: RequestScope, blog: Blog, post: BlogPost
) -> BlogPost:
    """Back to ``draft`` (or ``unpublished`` when it was published once)."""
    now = utcnow()
    post.status = _next(post, 'unarchive')
    _touch(post, scope.user_id, now)
    await session.flush()
    return post


@db_context_session(auto_commit=True)
async def publish_due(
    now: datetime | None = None,
    *,
    limit: int = 100,
    tenant_id: UUID | None = None,
    session: DBAsyncScopedSession | None = None,
) -> list[UUID]:
    """Publish every scheduled post whose ``scheduled_at`` ≤ ``now`` (Blog-0103) and return their ids.

    Idempotent: a published post is no longer ``scheduled``; rows are claimed with ``FOR UPDATE SKIP LOCKED`` so
    several workers never publish the same post. A post that cannot be published (empty body after a schema change)
    goes back to ``draft`` with the reason in ``review_comment``; one whose media cannot reach the CDN stays
    scheduled (next run). ``published_at`` = the scheduled time. The release of every blog that changed is rebuilt.
    ``tenant_id`` limits the run to one tenant (per-tenant jobs, tests).
    """
    assert session is not None  # injected by db_context_session
    now = now or utcnow()
    conds = [
        BlogPost.status == 'scheduled',
        BlogPost.scheduled_at <= now,
        BlogPost.deleted_at.is_(None),
        Blog.deleted_at.is_(None),
        Blog.status == 'active',
    ]
    if tenant_id is not None:
        conds.append(BlogPost.tenant_id == tenant_id)
    rows = (
        await session.execute(
            select(BlogPost, Blog)
            .join(Blog, Blog.id == BlogPost.blog_id)
            .where(*conds)
            .order_by(BlogPost.scheduled_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=BlogPost)
        )
    ).all()
    published: list[UUID] = []
    changed: dict[UUID, Blog] = {}
    for post, blog in rows:
        when = post.scheduled_at or now
        try:
            await _go_live(session, blog, post, None, when)
        except ServiceUnavailableException:
            logger.warning(
                'blog.post.schedule_retry',
                extra={'post_id': str(post.id), 'error': 'CDN copy failed'},
            )
            continue
        except ClientException as error:
            post.status, post.scheduled_at, post.schedule_timezone = 'draft', None, None
            post.review_comment = f'scheduled publication failed: {error.detail}'[:2000]
            logger.warning(
                'blog.post.schedule_failed',
                extra={'post_id': str(post.id), 'error': error.detail},
            )
        else:
            published.append(post.id)
            changed[blog.id] = blog
            logger.info(
                'blog.post.published',
                extra={'post_id': str(post.id), 'scheduled': True},
            )
        _touch(post, None, now)
    await session.flush()
    for blog in changed.values():
        await rebuild_release(session, blog)
    return published
