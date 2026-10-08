"""Spaces (Kb-0100 / Kb-0101): tenant-wide directory, create (creator → ``kb_space_admin``), settings, delete.

``session`` = the request's DB session, ``scope`` = the verified caller.
"""

from __future__ import annotations

import uuid
from uuid import UUID

import msgspec
from db.models.knowledge import KbPage, KbSpace
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, select

from ews.security import RequestScope
from ews.shared import ConflictException, utcnow

from ._access import KB_SPACES, SpaceAccess, load_space, readable_spaces
from ._rules import (
    clean_color,
    clean_icon,
    clean_text,
    clean_visibility,
    slug_error,
    slugify,
)
from .schemas import KbSpaceCreate, KbSpaceOut, KbSpaceRefOut, KbSpaceUpdate

SPACE_SLUG_MAX = 60


async def published_counts(
    session: DBAsyncScopedSession, space_ids: list[UUID]
) -> dict[UUID, int]:
    if not space_ids:
        return {}
    rows = await session.execute(
        select(KbPage.space_id, func.count())
        .where(
            KbPage.space_id.in_(space_ids),
            KbPage.deleted_at.is_(None),
            KbPage.published_revision_id.is_not(None),
        )
        .group_by(KbPage.space_id)
    )
    return dict(rows.tuples().all())


def space_out(access: SpaceAccess, page_count: int = 0) -> KbSpaceOut:
    s = access.space
    return KbSpaceOut(
        id=str(s.id),
        slug=s.slug,
        name=s.name,
        description=s.description,
        icon=s.icon,
        color=s.color,
        visibility=s.visibility,  # type: ignore[arg-type]
        include_sub_orgs=s.include_sub_orgs,
        organization_id=str(access.org.id),
        organization_name=access.org.name,
        organization_slug=access.org.slug,
        page_count=page_count,
        role=access.role,
        permissions=sorted(access.permissions),
        created_by=str(s.created_by) if s.created_by else None,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def space_ref(space: KbSpace) -> KbSpaceRefOut:
    return KbSpaceRefOut(
        id=str(space.id),
        slug=space.slug,
        name=space.name,
        icon=space.icon,
        color=space.color,
        visibility=space.visibility,  # type: ignore[arg-type]
    )


async def space_detail(
    session: DBAsyncScopedSession, access: SpaceAccess
) -> KbSpaceOut:
    counts = await published_counts(session, [access.space.id])
    return space_out(access, counts.get(access.space.id, 0))


async def list_spaces(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[KbSpaceOut]:
    """The space directory: every space of the tenant the caller can read (not only the URL organization)."""
    spaces = await readable_spaces(session, scope)
    counts = await published_counts(session, [a.space.id for a in spaces])
    return [space_out(a, counts.get(a.space.id, 0)) for a in spaces]


async def _slug_taken(
    session: DBAsyncScopedSession,
    tenant_id: UUID,
    slug: str,
    exclude: UUID | None = None,
) -> bool:
    stmt = select(KbSpace.id).where(
        KbSpace.tenant_id == tenant_id,
        KbSpace.slug == slug,
        KbSpace.deleted_at.is_(None),
    )
    if exclude:
        stmt = stmt.where(KbSpace.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _slug(
    session: DBAsyncScopedSession,
    tenant_id: UUID,
    wanted: str | None,
    name: str,
    exclude: UUID | None = None,
) -> str:
    if wanted:
        if error := slug_error(wanted, SPACE_SLUG_MAX):
            raise ClientException(detail=error)
        if await _slug_taken(session, tenant_id, wanted, exclude):
            raise ConflictException(
                detail=f'a space already uses the slug {wanted}',
                extra={'code': 'slug_taken'},
            )
        return wanted
    base = slugify(name, SPACE_SLUG_MAX - 4) or 'space'
    slug, n = base, 2
    while await _slug_taken(session, tenant_id, slug, exclude):
        slug, n = f'{base}-{n}', n + 1
    return slug


async def create_space(
    session: DBAsyncScopedSession, scope: RequestScope, data: KbSpaceCreate
) -> SpaceAccess:
    """A space of the request's organization; the creator becomes its ``kb_space_admin`` (Kb-0101)."""
    name = clean_text(data.name, 'name', 120, required=True)
    assert name is not None
    visibility = clean_visibility(data.visibility)
    space = KbSpace(
        id=uuid.uuid7(),
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        name=name,
        slug=await _slug(session, scope.tenant_id, data.slug, name),
        description=clean_text(data.description, 'description', 500),
        icon=clean_icon(data.icon),
        color=clean_color(data.color),
        visibility=visibility,
        include_sub_orgs=bool(data.include_sub_orgs) and visibility == 'organization',
        created_by=scope.user_id,
        updated_by=scope.user_id,
    )
    session.add(space)
    await session.flush()
    await KB_SPACES.grant_creator(scope.user_id, space.id)
    return await load_space(session, scope, space.id)


async def update_space(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    access: SpaceAccess,
    data: KbSpaceUpdate,
) -> KbSpace:
    space = access.space
    if data.name is not None:
        name = clean_text(data.name, 'name', 120, required=True)
        assert name is not None
        space.name = name
    if data.slug is not None and data.slug != space.slug:
        space.slug = await _slug(
            session, space.tenant_id, data.slug, space.name, exclude=space.id
        )
    if data.description is not msgspec.UNSET:
        space.description = clean_text(data.description, 'description', 500)
    if data.icon is not msgspec.UNSET:
        space.icon = clean_icon(data.icon)
    if data.color is not msgspec.UNSET:
        space.color = clean_color(data.color)
    if data.visibility is not None:
        space.visibility = clean_visibility(data.visibility)
    if data.include_sub_orgs is not None:
        space.include_sub_orgs = data.include_sub_orgs
    if space.visibility != 'organization':
        space.include_sub_orgs = False
    space.updated_by, space.updated_at = scope.user_id, utcnow()
    await session.flush()
    return space


async def delete_space(
    session: DBAsyncScopedSession, scope: RequestScope, access: SpaceAccess
) -> None:
    """Soft delete; the space's grants are revoked (its pages become unreachable with it)."""
    space = access.space
    space.deleted_at, space.updated_by = utcnow(), scope.user_id
    await session.flush()
    await KB_SPACES.forget(space.id)
