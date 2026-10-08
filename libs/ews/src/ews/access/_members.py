"""Members of an object: one role per user on ``<kind>:<id>`` (app-roles-spec §5 assignment rules).

The user must belong to the request's organization or one of its sub-organizations; organization and
tenant admins are listed as inherited (they hold every right through the organization, read-only here).
"""

from __future__ import annotations

from uuid import UUID

from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import text

from ews.authz import ews_catalog, grant, grants_in, revoke
from ews.security import RequestScope
from ews.shared import parse_uuid

from ._object import ObjectAccess
from .schemas import CandidateOut, MemberOut, RoleOut

_INHERITED = ('org_admin', 'tenant_admin')


def object_roles(access: ObjectAccess) -> list[RoleOut]:
    """The kind's catalog roles, highest first (for the role picker)."""
    raw = {r.key: r for r in ews_catalog().roles if r.scope == access.kind}
    return [
        RoleOut(
            key=key,
            name=raw[key].name or key,
            description=raw[key].description or '',
            rank=access.rank(key),
            default=key == access.default_role,
        )
        for key in access.roles
    ]


async def _users(
    session: DBAsyncScopedSession, ids: set[str]
) -> dict[str, tuple[str | None, str | None]]:
    uuids: list[UUID] = []
    for i in ids:
        try:
            uuids.append(UUID(i))
        except ValueError:
            continue
    if not uuids:
        return {}
    rows = await session.execute(
        text('select id, email, name from taas_user_account where id = any(:ids)'),
        {'ids': uuids},
    )
    return {str(r.id): (r.email, r.name) for r in rows}


async def list_members(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    access: ObjectAccess,
    object_id: UUID | str,
    *,
    org_domains: list[str] | None = None,
) -> list[MemberOut]:
    """Direct members (highest role first), then the inherited organization / tenant admins."""
    roles = set(access.roles)
    direct = [
        (u, r) for u, r, _ in await grants_in([access.domain(object_id)]) if r in roles
    ]
    inherited = [
        (u, r)
        for u, r, _ in await grants_in(org_domains or scope.org_domains())
        if r in _INHERITED
    ]
    users = await _users(session, {u for u, _ in direct} | {u for u, _ in inherited})
    out = [
        MemberOut(
            user_id=u,
            email=users.get(u, (None, None))[0],
            name=users.get(u, (None, None))[1],
            role=r,
        )
        for u, r in sorted(direct, key=lambda x: -access.rank(x[1]))
    ]
    seen = {m.user_id for m in out}
    for u, r in inherited:
        if u not in seen:
            seen.add(u)
            email, name = users.get(u, (None, None))
            out.append(
                MemberOut(user_id=u, email=email, name=name, role=r, inherited=True)
            )
    return out


async def member_candidates(
    session: DBAsyncScopedSession, scope: RequestScope, q: str | None, limit: int = 20
) -> list[CandidateOut]:
    """Members of the request's organization and its sub-organizations matching ``q`` (e-mail or name)."""
    like = f'%{(q or "").strip().lower()}%'
    rows = await session.execute(
        text(
            'select distinct u.id, u.email, u.name from taas_organization_members m '
            'join taas_organizations o on o.id = m.organization_id '
            'join taas_user_account u on u.id = m.user_id '
            'where m.tenant_id = :t and o.path like :path '
            "and (lower(u.email) like :q or lower(coalesce(u.name, '')) like :q) "
            'order by u.email limit :limit'
        ),
        {
            't': scope.tenant_id,
            'path': f'%/{scope.organization_id}/%',
            'q': like,
            'limit': min(limit, 100),
        },
    )
    return [CandidateOut(user_id=str(r.id), email=r.email, name=r.name) for r in rows]


async def upsert_member(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    access: ObjectAccess,
    object_id: UUID | str,
    user_id: str,
    role: str,
) -> MemberOut:
    """Grant ``role`` (replacing the user's other role of the kind); 400 for a user outside the organization."""
    access.require_role(role)
    uid = parse_uuid(user_id, 'user', not_found=False)
    row = (
        await session.execute(
            text(
                'select u.email, u.name from taas_organization_members m '
                'join taas_organizations o on o.id = m.organization_id '
                'join taas_user_account u on u.id = m.user_id '
                'where m.user_id = :u and m.tenant_id = :t and o.path like :path limit 1'
            ),
            {'u': uid, 't': scope.tenant_id, 'path': f'%/{scope.organization_id}/%'},
        )
    ).first()
    if row is None:
        raise ClientException(
            detail='the user is not a member of this organization: invite them first'
        )
    domain = access.domain(object_id)
    for _, current, _ in await grants_in([domain], user_id=uid):
        if current in access.roles and current != role:
            await revoke(uid, current, domain)
    await grant(uid, role, domain)
    return MemberOut(user_id=str(uid), email=row.email, name=row.name, role=role)


async def remove_member(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    access: ObjectAccess,
    object_id: UUID | str,
    user_id: str,
) -> None:
    """Revoke the user's roles of the kind on the object; 404 when it has none."""
    del session, scope  # same signature as the other member operations
    uid = parse_uuid(user_id, 'user', not_found=False)
    domain = access.domain(object_id)
    roles = [
        r for _, r, _ in await grants_in([domain], user_id=uid) if r in access.roles
    ]
    if not roles:
        raise NotFoundException(detail='member not found')
    for role in roles:
        await revoke(uid, role, domain)
