"""``ObjectAccess``: who may do what on a business object with its own RBAC domain."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from uuid import UUID

from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)

from ews.authz import (
    ews_catalog,
    grant,
    granted_permissions,
    resource_domains,
    revoke_domain,
    user_domains,
)
from ews.security import RequestScope, is_allowed


@cache
def role_permissions(role: str) -> frozenset[str]:
    """Every ``<resource>:<action>`` a role of the EWS catalog grants (wildcards expanded)."""
    catalog = ews_catalog()
    granted: set[str] = set()
    for r in catalog.roles:
        if r.key != role:
            continue
        for permission in r.permissions:
            resource, _, action = permission.rpartition(':')
            resources = list(catalog.resources) if resource == '*' else [resource]
            for res in resources:
                actions = catalog.resources.get(res, ())
                granted.update(f'{res}:{a}' for a in actions if action in ('*', a))
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class ObjectAccess:
    """Access rules of one object kind, e.g. ``ObjectAccess('drive', 'files.drive', 'files')``.

    - Domains: ``<kind>:<id>`` → the organization chain (of the object's organization when ``org_path``
      is given, else of the request) → ``tenant:<id>``; roles of the kind are the catalog roles whose
      ``scope`` is ``kind`` (highest first, catalog order).
    - ``implicit_role``: a role the caller holds without a grant (a space's visibility audience, the
      members of an organization drive) — its catalog permissions are added to the casbin decision.
    - ``check``: not readable → 404 (no hint that the object exists); readable without the right → 403.
    - Development mode (``scope.is_dev``) allows everything, like ``ews.security.is_allowed``.
    """

    kind: str
    """RBAC domain kind = the catalog role scope: ``drive``, ``kb-space``, ``blog``."""
    resource: str
    """Resource whose ``read`` makes the object visible: ``files.drive``, ``kb.space``, ``blog.blog``."""
    namespace: str
    """Catalog namespace of the app: ``files``, ``kb``, ``blog``."""
    default_role: str | None = None
    """Role preselected when adding a member."""

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(r.key for r in ews_catalog().roles if r.scope == self.kind)

    def rank(self, role: str) -> int:
        roles = self.roles
        return (len(roles) - roles.index(role)) * 10 if role in roles else 0

    def domain(self, object_id: UUID | str) -> str:
        return f'{self.kind}:{object_id}'

    def domains(
        self, scope: RequestScope, object_id: UUID | str, *, org_path: str | None = None
    ) -> list[str]:
        orgs = (
            scope.org_domains()
            if org_path is None
            else resource_domains(tenant_id=scope.tenant_id, org_path=org_path)
        )
        return [self.domain(object_id), *orgs]

    async def allowed(
        self,
        scope: RequestScope,
        object_id: UUID | str,
        resource: str,
        action: str,
        *,
        implicit_role: str | None = None,
        org_path: str | None = None,
    ) -> bool:
        if implicit_role and f'{resource}:{action}' in role_permissions(implicit_role):
            return True
        return await is_allowed(
            scope, resource, action, self.domains(scope, object_id, org_path=org_path)
        )

    async def require(
        self,
        scope: RequestScope,
        object_id: UUID | str,
        resource: str,
        action: str,
        *,
        implicit_role: str | None = None,
        org_path: str | None = None,
    ) -> None:
        """403 unless allowed (use when the object is already known to be visible)."""
        if not await self.allowed(
            scope,
            object_id,
            resource,
            action,
            implicit_role=implicit_role,
            org_path=org_path,
        ):
            raise PermissionDeniedException(
                detail=f'missing permission {resource}:{action}'
            )

    async def check(
        self,
        scope: RequestScope,
        object_id: UUID | str,
        resource: str,
        action: str,
        *,
        implicit_role: str | None = None,
        org_path: str | None = None,
        what: str | None = None,
    ) -> None:
        """404 when the caller cannot read the object, 403 when it can read it but not ``resource:action``."""
        kw = {'implicit_role': implicit_role, 'org_path': org_path}
        if await self.allowed(scope, object_id, resource, action, **kw):
            return
        if (resource, action) == (self.resource, 'read') or not await self.allowed(
            scope, object_id, self.resource, 'read', **kw
        ):
            raise NotFoundException(detail=f'{what or self.kind} not found')
        raise PermissionDeniedException(
            detail=f'missing permission {resource}:{action}'
        )

    async def permissions(
        self,
        scope: RequestScope,
        object_id: UUID | str,
        *,
        implicit_role: str | None = None,
        org_path: str | None = None,
    ) -> set[str]:
        """The caller's ``<resource>:<action>`` of the app's namespace on the object (UI hints only)."""
        prefix = f'{self.namespace}.'
        if scope.is_dev:
            return {
                f'{res}:{a}'
                for res, actions in ews_catalog().resources.items()
                if res.startswith(prefix)
                for a in actions
            }
        granted = await granted_permissions(
            scope.user_id,
            self.domains(scope, object_id, org_path=org_path),
            self.namespace,
        )
        if implicit_role:
            granted |= {
                p for p in role_permissions(implicit_role) if p.startswith(prefix)
            }
        return granted

    async def role_of(self, user_id: UUID | str, object_id: UUID | str) -> str | None:
        """The user's direct role on the object (highest when several)."""
        domain = self.domain(object_id)
        roles = [
            r
            for d, r in (await user_domains(user_id, domain)).items()
            if d == domain and r in self.roles
        ]
        return max(roles, key=self.rank) if roles else None

    async def shared_with(self, user_id: UUID | str) -> dict[UUID, str]:
        """``{object id: role}`` of the objects of this kind the user holds a role on (list queries)."""
        out: dict[UUID, str] = {}
        roles = set(self.roles)
        for domain, role in (await user_domains(user_id, f'{self.kind}:')).items():
            if role not in roles:
                continue
            try:
                out[UUID(domain.removeprefix(f'{self.kind}:'))] = role
            except ValueError:
                continue
        return out

    async def grant_creator(self, user_id: UUID | str, object_id: UUID | str) -> None:
        """The creator gets the highest role of the kind on the new object."""
        await grant(user_id, self.roles[0], self.domain(object_id))

    async def forget(self, object_id: UUID | str) -> None:
        """Remove every grant on the object (it was deleted)."""
        await revoke_domain(self.domain(object_id))

    def require_role(self, role: str) -> str:
        if role not in self.roles:
            raise ClientException(detail=f'role must be one of {", ".join(self.roles)}')
        return role
