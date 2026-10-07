"""Who may do what on a site: permissions on ``site:<id>`` → organization chain → tenant (Iam-07xx).

Sites belong to the organization of the request (``/<org>/sites``): a site of another organization is
a 404, never a 403 (no hint that it exists).
"""

from __future__ import annotations

from uuid import UUID

from db.models.sites import Site
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException, PermissionDeniedException
from sqlalchemy import select

from ews.authz import EwsResources, SiteRoles, ews_catalog, granted_permissions, user_domains
from ews.security import RequestScope, is_allowed
from ews.shared import parse_uuid

SITE = EwsResources.SITE.value
PAGE = EwsResources.SITE_PAGE.value


def site_domains(scope: RequestScope, site_id: UUID | str) -> list[str]:
    return [f'site:{site_id}', *scope.org_domains()]


def all_site_permissions() -> set[str]:
    return {
        f'{resource}:{action}'
        for resource, actions in ews_catalog().resources.items()
        if resource.startswith('sites.')
        for action in actions
    }


async def permissions_on(scope: RequestScope, site_id: UUID | str) -> set[str]:
    if scope.is_dev:
        return all_site_permissions()
    return await granted_permissions(scope.user_id, site_domains(scope, site_id), 'sites')


async def role_on(scope: RequestScope, site_id: UUID | str) -> str | None:
    if scope.is_dev:
        return None
    return (await user_domains(scope.user_id, f'site:{site_id}')).get(f'site:{site_id}')


async def require(scope: RequestScope, site_id: UUID | str, resource: str, action: str) -> None:
    if not await is_allowed(scope, resource, action, site_domains(scope, site_id)):
        raise PermissionDeniedException(detail=f'missing permission {resource}:{action}')


async def load_site(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    site_id: object,
    resource: str = SITE,
    action: str = 'read',
    *,
    include_archived: bool = True,
) -> Site:
    """A site of the request's organization the caller may ``resource:action`` (404 / 403)."""
    sid = parse_uuid(site_id, 'site')
    site = await session.scalar(
        select(Site).where(
            Site.id == sid,
            Site.tenant_id == scope.tenant_id,
            Site.organization_id == scope.organization_id,
            Site.deleted_at.is_(None),
        )
    )
    if site is None or (not include_archived and site.status == 'archived'):
        raise NotFoundException(detail='site not found')
    if not await is_allowed(scope, resource, action, site_domains(scope, site.id)):
        if not await is_allowed(scope, SITE, 'read', site_domains(scope, site.id)):
            raise NotFoundException(detail='site not found')
        raise PermissionDeniedException(detail=f'missing permission {resource}:{action}')
    return site


async def readable_site_ids(scope: RequestScope) -> set[UUID] | None:
    """``None`` = every site of the organization (organization-level read), else the granted sites."""
    if await is_allowed(scope, SITE, 'read'):
        return None
    granted = await user_domains(scope.user_id, 'site:')
    roles = {r.value for r in SiteRoles}
    return {UUID(d.split(':', 1)[1]) for d, role in granted.items() if role in roles}
