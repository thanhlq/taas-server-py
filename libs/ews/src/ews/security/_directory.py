"""Read-only view of the shared IAM directory tables (owned by the IAM, DDL in ``libs/db``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import text


@dataclass(frozen=True, slots=True)
class DirectoryUser:
    id: UUID
    email: str
    name: str | None
    tenant_id: UUID | None


@dataclass(frozen=True, slots=True)
class DirectoryOrganization:
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    path: str
    """Materialized path ``/<root>/<child>/`` (RBAC domain chain)."""
    depth: int


@dataclass(frozen=True, slots=True)
class DirectoryMembership:
    organization: DirectoryOrganization
    role: str
    """``tenant_admin`` · ``org_admin`` · ``org_member``."""


class DirectoryT(ABC):
    @abstractmethod
    async def user_by_subject(self, subject: str) -> DirectoryUser | None: ...

    @abstractmethod
    async def user_by_email(self, email: str) -> DirectoryUser | None: ...

    @abstractmethod
    async def memberships(self, user_id: UUID) -> list[DirectoryMembership]: ...

    @abstractmethod
    async def organization(self, organization_id: UUID) -> DirectoryOrganization | None: ...

    @abstractmethod
    async def organization_by_slug(self, slug: str) -> DirectoryOrganization | None:
        """The organization of the URL ``/<slug>/…`` (slugs are unique across tenants)."""

    @abstractmethod
    async def first_root_organization(self, slug: str | None = None) -> DirectoryOrganization | None:
        """Development fallback: the organization with ``slug`` (else the oldest root organization)."""


_ORG_COLUMNS = 'o.id, o.tenant_id, o.slug, coalesce(o.name, o.slug) as name, o.path, o.depth'


def _org(row) -> DirectoryOrganization:  # noqa: ANN001
    return DirectoryOrganization(
        id=row.id, tenant_id=row.tenant_id, slug=row.slug, name=row.name, path=row.path, depth=row.depth
    )


class SqlDirectory(DirectoryT):
    """``taas_user_account``, ``taas_organizations``, ``taas_organization_members`` (shared Postgres)."""

    @db_context_session
    async def user_by_subject(
        self, subject: str, *, session: DBAsyncScopedSession | None = None
    ) -> DirectoryUser | None:
        assert session is not None
        row = (
            await session.execute(
                text('select id, email, name, tenant_id from taas_user_account where directory_id = :s'),
                {'s': subject},
            )
        ).first()
        return DirectoryUser(id=row.id, email=row.email, name=row.name, tenant_id=row.tenant_id) if row else None

    @db_context_session
    async def user_by_email(
        self, email: str, *, session: DBAsyncScopedSession | None = None
    ) -> DirectoryUser | None:
        assert session is not None
        row = (
            await session.execute(
                text('select id, email, name, tenant_id from taas_user_account where lower(email) = lower(:e)'),
                {'e': email},
            )
        ).first()
        return DirectoryUser(id=row.id, email=row.email, name=row.name, tenant_id=row.tenant_id) if row else None

    @db_context_session
    async def memberships(
        self, user_id: UUID, *, session: DBAsyncScopedSession | None = None
    ) -> list[DirectoryMembership]:
        assert session is not None
        rows = await session.execute(
            text(
                f'select {_ORG_COLUMNS}, m.role from taas_organization_members m '
                'join taas_organizations o on o.id = m.organization_id '
                'where m.user_id = :u and o.deleted_at is null order by o.depth, m.created_at'
            ),
            {'u': user_id},
        )
        return [DirectoryMembership(organization=_org(r), role=r.role) for r in rows]

    @db_context_session
    async def organization(
        self, organization_id: UUID, *, session: DBAsyncScopedSession | None = None
    ) -> DirectoryOrganization | None:
        assert session is not None
        row = (
            await session.execute(
                text(f'select {_ORG_COLUMNS} from taas_organizations o where o.id = :id and o.deleted_at is null'),
                {'id': organization_id},
            )
        ).first()
        return _org(row) if row else None

    @db_context_session
    async def organization_by_slug(
        self, slug: str, *, session: DBAsyncScopedSession | None = None
    ) -> DirectoryOrganization | None:
        assert session is not None
        row = (
            await session.execute(
                text(f'select {_ORG_COLUMNS} from taas_organizations o where o.slug = :s and o.deleted_at is null'),
                {'s': slug},
            )
        ).first()
        return _org(row) if row else None

    @db_context_session
    async def first_root_organization(
        self, slug: str | None = None, *, session: DBAsyncScopedSession | None = None
    ) -> DirectoryOrganization | None:
        assert session is not None
        if slug:
            row = (
                await session.execute(
                    text(f'select {_ORG_COLUMNS} from taas_organizations o where o.slug = :s and o.deleted_at is null'), {'s': slug}
                )
            ).first()
            if row:
                return _org(row)
        row = (
            await session.execute(
                text(f'select {_ORG_COLUMNS} from taas_organizations o where o.depth = 0 and o.deleted_at is null order by o.created_at limit 1')
            )
        ).first()
        return _org(row) if row else None
