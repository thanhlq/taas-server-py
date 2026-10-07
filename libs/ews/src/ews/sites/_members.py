"""Site members: app roles of ``sites`` granted on ``site:<id>`` (app-roles-spec §5 assignment rules).

One role per user and site; the user must belong to the site's organization (or a sub-organization);
organization / tenant admins are listed as inherited (read-only here).
"""

from __future__ import annotations

from uuid import UUID

from db.models.sites import Site
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import text

from ews.authz import SiteRoles, grant, grants_in, revoke
from ews.security import RequestScope
from ews.shared import parse_uuid

from ._audit import audit
from .schemas import CandidateOut, MemberOut, RoleOut

ROLE_RANK = {
    SiteRoles.SITE_ADMIN.value: 80,
    SiteRoles.SITE_EDITOR.value: 60,
    SiteRoles.SITE_AUTHOR.value: 40,
    SiteRoles.SITE_VIEWER.value: 10,
}
DEFAULT_ROLE = SiteRoles.SITE_AUTHOR.value


def site_roles() -> list[RoleOut]:
    raw = {r['key']: r for r in _catalog_roles()}
    return [
        RoleOut(key=key, name=raw[key].get('name', key), description=raw[key].get('description', ''), rank=rank, default=key == DEFAULT_ROLE)
        for key, rank in sorted(ROLE_RANK.items(), key=lambda kv: -kv[1])
    ]


def _catalog_roles() -> list[dict]:
    import json
    from pathlib import Path

    import ews.authz as authz

    path = Path(authz.__file__).parent / 'data' / 'ews-rbac.json'
    return [r for r in json.loads(path.read_text(encoding='utf-8'))['roles'] if r.get('scope') == 'site']


async def _users(session: DBAsyncScopedSession, ids: set[str]) -> dict[str, tuple[str, str | None]]:
    if not ids:
        return {}
    uuids = []
    for i in ids:
        try:
            uuids.append(UUID(i))
        except ValueError:
            continue
    rows = await session.execute(text('select id, email, name from taas_user_account where id = any(:ids)'), {'ids': uuids})
    return {str(r.id): (r.email, r.name) for r in rows}


async def list_members(session: DBAsyncScopedSession, scope: RequestScope, site: Site) -> list[MemberOut]:
    direct = [(u, r) for u, r, _ in await grants_in([f'site:{site.id}']) if r in ROLE_RANK]
    inherited = [
        (u, r) for u, r, _ in await grants_in(scope.org_domains()) if r in ('org_admin', 'tenant_admin')
    ]
    users = await _users(session, {u for u, _ in direct} | {u for u, _ in inherited})
    out = [
        MemberOut(user_id=u, email=users.get(u, (None, None))[0], name=users.get(u, (None, None))[1], role=r)
        for u, r in sorted(direct, key=lambda x: -ROLE_RANK[x[1]])
    ]
    seen = {m.user_id for m in out}
    for u, r in inherited:
        if u not in seen:
            seen.add(u)
            out.append(MemberOut(user_id=u, email=users.get(u, (None, None))[0], name=users.get(u, (None, None))[1], role=r, inherited=True))
    return out


async def candidates(session: DBAsyncScopedSession, scope: RequestScope, q: str | None, limit: int = 20) -> list[CandidateOut]:
    """Members of the site's organization and its sub-organizations."""
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
        {'t': scope.tenant_id, 'path': f'%/{scope.organization_id}/%', 'q': like, 'limit': min(limit, 100)},
    )
    return [CandidateOut(user_id=str(r.id), email=r.email, name=r.name) for r in rows]


async def upsert_member(session: DBAsyncScopedSession, scope: RequestScope, site: Site, user_id: str, role: str) -> MemberOut:
    if role not in ROLE_RANK:
        raise ClientException(detail=f'role must be one of {", ".join(ROLE_RANK)}')
    uid = parse_uuid(user_id, 'user', not_found=False)
    member = await session.execute(
        text(
            'select u.email, u.name from taas_organization_members m '
            'join taas_organizations o on o.id = m.organization_id '
            'join taas_user_account u on u.id = m.user_id '
            'where m.user_id = :u and m.tenant_id = :t and o.path like :path limit 1'
        ),
        {'u': uid, 't': scope.tenant_id, 'path': f'%/{scope.organization_id}/%'},
    )
    row = member.first()
    if row is None:
        raise ClientException(detail='the user is not a member of this organization: invite them first')
    domain = f'site:{site.id}'
    for _, current, _ in await grants_in([domain], user_id=uid):
        if current in ROLE_RANK and current != role:
            await revoke(uid, current, domain)
    await grant(uid, role, domain)
    audit(session, scope, 'member.granted', site_id=site.id, target_type='user', target_id=uid, role=role)
    await session.flush()
    return MemberOut(user_id=str(uid), email=row.email, name=row.name, role=role)


async def remove_member(session: DBAsyncScopedSession, scope: RequestScope, site: Site, user_id: str) -> None:
    uid = parse_uuid(user_id, 'user', not_found=False)
    domain = f'site:{site.id}'
    roles = [r for _, r, _ in await grants_in([domain], user_id=uid) if r in ROLE_RANK]
    if not roles:
        raise NotFoundException(detail='member not found')
    for role in roles:
        await revoke(uid, role, domain)
    audit(session, scope, 'member.revoked', site_id=site.id, target_type='user', target_id=uid)
    await session.flush()
