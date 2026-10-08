"""Top-level path segments of an organization's public host (``<org>.<SITES_DOMAIN>/<slug>``).

Sites and blogs (and every future app served at the organization's address) share one namespace: a slug
used by one may not be used by another. Add the model of a new app to ``PATH_OWNERS``.
"""

from __future__ import annotations

from uuid import UUID

from db.models.blog import Blog
from db.models.sites import Site
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import select

PATH_OWNERS = (Site, Blog)
"""Models with ``id``, ``organization_id``, ``slug`` and ``deleted_at`` served at ``<org host>/<slug>``."""


async def path_segment_taken(
    session: DBAsyncScopedSession,
    organization_id: UUID,
    slug: str,
    *,
    exclude: UUID | None = None,
) -> bool:
    """A live site, blog, … of the organization already uses ``slug`` (``exclude`` = the object being renamed)."""
    for model in PATH_OWNERS:
        stmt = select(model.id).where(
            model.organization_id == organization_id,
            model.slug == slug,
            model.deleted_at.is_(None),
        )
        if exclude is not None:
            stmt = stmt.where(model.id != exclude)
        if (await session.scalar(stmt.limit(1))) is not None:
            return True
    return False
