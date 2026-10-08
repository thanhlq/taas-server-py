"""Who may do what in the Knowledge Center (Kb-0100…0104).

- Domains: ``kb-space:<id>`` → the chain of the **space's** organization → ``tenant:<id>`` (``KB_SPACES``,
  ``ews.access.ObjectAccess``). Space roles ``kb_space_admin`` · ``kb_space_editor`` · ``kb_space_viewer``;
  ``org_admin`` of the space's organization (or an ancestor) and the tenant's ``kb_admin`` / ``tenant_admin`` hold
  every right through the chain.
- Visibility grants ``kb_space_viewer`` implicitly (``_rules.implicit_role``): ``tenant`` → every user of the
  tenant, ``organization`` → members of the space's organization (+ sub-organizations when ``include_sub_orgs``),
  ``restricted`` → explicit members only.
- Spaces are tenant-wide: a space is found by id in the caller's tenant whatever the URL organization; another
  tenant's or an unreadable space → 404, readable without the right → 403 (``ObjectAccess.check`` rule).
- Pages inherit the space; a never-published page is a draft, visible to editors (``kb.page:update``) only.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from uuid import UUID

from db.models.knowledge import KbPage, KbSpace
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException, PermissionDeniedException
from sqlalchemy import select, text

from ews.access import ObjectAccess, role_permissions
from ews.authz import EwsResources, ews_catalog, granted_permissions, resource_domains
from ews.security import DirectoryOrganization, RequestScope
from ews.shared import parse_uuid

from ._rules import implicit_role

KB_SPACES = ObjectAccess(
    'kb-space', EwsResources.KB_SPACE.value, 'kb', default_role='kb_space_editor'
)
SPACE = EwsResources.KB_SPACE.value
SPACE_MEMBER = EwsResources.KB_SPACE_MEMBER.value
PAGE = EwsResources.KB_PAGE.value

_ORG_COLUMNS = (
    'o.id, o.tenant_id, o.slug, coalesce(o.name, o.slug) as name, o.path, o.depth'
)


def all_permissions() -> frozenset[str]:
    """Every ``kb.*`` permission of the catalog (development mode)."""
    return frozenset(
        f'{resource}:{action}'
        for resource, actions in ews_catalog().resources.items()
        if resource.startswith('kb.')
        for action in actions
    )


@dataclass(slots=True)
class SpaceAccess:
    """A space with its organization and the caller's rights on it."""

    space: KbSpace
    org: DirectoryOrganization
    permissions: frozenset[str]
    role: str | None = None
    """Direct role, else the implicit viewer role, else ``None`` (organization / tenant role)."""

    def can(self, resource: str, action: str) -> bool:
        return f'{resource}:{action}' in self.permissions

    @property
    def is_editor(self) -> bool:
        """Sees drafts (Kb-0103)."""
        return self.can(PAGE, 'update')

    def require(self, resource: str, action: str, what: str = 'space') -> None:
        """404 when the caller cannot read the space, 403 when it lacks ``resource:action``."""
        if not self.can(SPACE, 'read'):
            raise NotFoundException(detail=f'{what} not found')
        if not self.can(resource, action):
            raise PermissionDeniedException(
                detail=f'missing permission {resource}:{action}'
            )

    def member_scope(self, scope: RequestScope) -> RequestScope:
        """``scope`` moved to the space's organization: member candidates / grants come from its subtree, inherited
        admins from its chain (``ews.access`` members routes)."""
        return dataclasses.replace(scope, organization=self.org)


@dataclass(slots=True)
class PageAccess:
    page: KbPage
    access: SpaceAccess

    @property
    def space(self) -> KbSpace:
        return self.access.space


def _org(row) -> DirectoryOrganization:  # noqa: ANN001
    return DirectoryOrganization(
        id=row.o_id,
        tenant_id=row.o_tenant_id,
        slug=row.o_slug,
        name=row.o_name,
        path=row.o_path,
        depth=row.o_depth,
    )


async def _organizations(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[UUID, DirectoryOrganization]:
    if not ids:
        return {}
    rows = await session.execute(
        text(
            'select o.id as o_id, o.tenant_id as o_tenant_id, o.slug as o_slug, coalesce(o.name, o.slug) as o_name, '
            'o.path as o_path, o.depth as o_depth from taas_organizations o where o.id = any(:ids) and o.deleted_at is null'
        ),
        {'ids': list(ids)},
    )
    return {r.o_id: _org(r) for r in rows}


async def _organization(
    session: DBAsyncScopedSession, organization_id: UUID
) -> DirectoryOrganization | None:
    return (await _organizations(session, {organization_id})).get(organization_id)


async def memberships(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[tuple[UUID, str]]:
    """``(organization id, path)`` of the caller's organizations in the request's tenant."""
    rows = await session.execute(
        text(
            'select o.id, o.path from taas_organization_members m join taas_organizations o on o.id = m.organization_id '
            'where m.user_id = :u and m.tenant_id = :t and o.deleted_at is null'
        ),
        {'u': scope.user_id, 't': scope.tenant_id},
    )
    return [(r.id, r.path) for r in rows]


async def _access_of(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    space: KbSpace,
    org: DirectoryOrganization,
) -> SpaceAccess:
    if scope.is_dev:
        return SpaceAccess(space=space, org=org, permissions=all_permissions())
    implicit = implicit_role(space, org.path, await memberships(session, scope))
    permissions = await KB_SPACES.permissions(
        scope, space.id, implicit_role=implicit, org_path=org.path
    )
    role = await KB_SPACES.role_of(scope.user_id, space.id) or implicit
    return SpaceAccess(
        space=space, org=org, permissions=frozenset(permissions), role=role
    )


async def load_space(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    space_id: object,
    resource: str = SPACE,
    action: str = 'read',
) -> SpaceAccess:
    """A live space of the caller's tenant the caller may ``resource:action`` (404 / 403)."""
    sid = parse_uuid(space_id, 'space')
    space = await session.scalar(
        select(KbSpace).where(
            KbSpace.id == sid,
            KbSpace.tenant_id == scope.tenant_id,
            KbSpace.deleted_at.is_(None),
        )
    )
    org = await _organization(session, space.organization_id) if space else None
    if space is None or org is None:
        raise NotFoundException(detail='space not found')
    access = await _access_of(session, scope, space, org)
    access.require(resource, action)
    return access


async def load_page(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    page_id: object,
    resource: str = PAGE,
    action: str = 'read',
) -> PageAccess:
    """A live page of a readable space; drafts (never published) are 404 for readers (Kb-0103)."""
    pid = parse_uuid(page_id, 'page')
    row = (
        await session.execute(
            select(KbPage, KbSpace)
            .join(KbSpace, KbSpace.id == KbPage.space_id)
            .where(
                KbPage.id == pid,
                KbPage.tenant_id == scope.tenant_id,
                KbPage.deleted_at.is_(None),
                KbSpace.deleted_at.is_(None),
            )
        )
    ).first()
    org = await _organization(session, row[1].organization_id) if row else None
    if row is None or org is None:
        raise NotFoundException(detail='page not found')
    page, space = row
    access = await _access_of(session, scope, space, org)
    if not access.can(SPACE, 'read') or (
        page.published_revision_id is None and not access.is_editor
    ):
        raise NotFoundException(detail='page not found')
    access.require(resource, action, 'page')
    return PageAccess(page=page, access=access)


async def readable_spaces(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    space_ids: list[UUID] | None = None,
) -> list[SpaceAccess]:
    """Every live space of the tenant the caller can read (Kb-0104 list trimming), by name.

    Batched: one query for the caller's memberships, one for its space roles, one per distinct space organization
    (organization / tenant roles) — same decision as ``load_space``.
    """
    stmt = select(KbSpace).where(
        KbSpace.tenant_id == scope.tenant_id, KbSpace.deleted_at.is_(None)
    )
    if space_ids is not None:
        stmt = stmt.where(KbSpace.id.in_(space_ids))
    spaces = list(await session.scalars(stmt.order_by(KbSpace.name, KbSpace.id)))
    orgs = await _organizations(session, {s.organization_id for s in spaces})
    if scope.is_dev:
        everything = all_permissions()
        return [
            SpaceAccess(space=s, org=orgs[s.organization_id], permissions=everything)
            for s in spaces
            if s.organization_id in orgs
        ]
    mine = await memberships(session, scope)
    direct = await KB_SPACES.shared_with(scope.user_id)
    by_org: dict[str, frozenset[str]] = {}
    out: list[SpaceAccess] = []
    for space in spaces:
        org = orgs.get(space.organization_id)
        if org is None:
            continue
        if org.path not in by_org:
            domains = resource_domains(tenant_id=scope.tenant_id, org_path=org.path)
            by_org[org.path] = frozenset(
                await granted_permissions(scope.user_id, domains, 'kb')
            )
        implicit = implicit_role(space, org.path, mine)
        role = direct.get(space.id)
        permissions = by_org[org.path] | (
            role_permissions(role) if role else frozenset()
        )
        permissions |= role_permissions(implicit) if implicit else frozenset()
        if f'{SPACE}:read' in permissions:
            out.append(
                SpaceAccess(
                    space=space, org=org, permissions=permissions, role=role or implicit
                )
            )
    return out
