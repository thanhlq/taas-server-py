"""Domain RBAC on ``taas_casbin_rule`` for the EWS apps (mirror of ``@taas/iam-db`` ``CasbinRbac``).

The ``session`` parameters are injected by ``db_context_session``: never pass them.

- ``sync_catalog``: bootstrap at start-up — the stored ``p`` rows of the catalog's roles become the
  catalog (``ews-rbac.json``); rows of other catalogs (IAM) and custom roles are untouched.
- ``can``: grants (``g, <user_id>, <role>, <domain>``) read fresh on every check; policies = this
  catalog + the other stored ``p`` rows (IAM built-in roles synced by the IAM, custom roles), cached
  per process.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from db.models.core import CasbinRule
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import delete, select, text

from ._catalog import (
    PolicyRow,
    RbacCatalog,
    catalog_owns_policy,
    catalog_policies,
    evaluate,
    ews_catalog,
)

# Same lock as the IAM sync (Node): one catalog sync at a time across services / replicas.
_SYNC_LOCK = text("select pg_advisory_xact_lock(hashtext('taas_rbac_catalog_sync'))")

_policies: list[PolicyRow] | None = None


@dataclass(frozen=True)
class SyncResult:
    added: int
    removed: int


def _row(rule: CasbinRule) -> tuple[str, str, str, str]:
    return (rule.v0 or '', rule.v1 or '', rule.v2 or '', rule.v3 or '')


@db_context_session(auto_commit=True)
async def sync_catalog(
    catalog: RbacCatalog | None = None, *, session: DBAsyncScopedSession | None = None
) -> SyncResult:
    """Idempotent bootstrap of the catalog's ``p`` rows (default: ``ews-rbac.json``)."""
    assert session is not None  # injected by db_context_session
    global _policies
    catalog = catalog or ews_catalog()
    desired = catalog_policies(catalog)
    await session.execute(_SYNC_LOCK)
    stored = (
        await session.scalars(select(CasbinRule).where(CasbinRule.ptype == 'p'))
    ).all()
    have: set[PolicyRow] = set()
    stale: list[int] = []
    for rule in stored:
        row = _row(rule)
        if not catalog_owns_policy(catalog, row):
            continue
        if row in desired and row not in have:
            have.add(row)
        else:
            stale.append(rule.id)
    missing = [p for p in desired if p not in have]
    if stale:
        await session.execute(delete(CasbinRule).where(CasbinRule.id.in_(stale)))
    for v0, v1, v2, v3 in missing:
        session.add(CasbinRule(ptype='p', v0=v0, v1=v1, v2=v2, v3=v3))
    await session.flush()
    _policies = None
    return SyncResult(added=len(missing), removed=len(stale))


async def _load_policies(session: DBAsyncScopedSession) -> list[PolicyRow]:
    global _policies
    if _policies is None:
        catalog = ews_catalog()
        stored = (
            await session.scalars(select(CasbinRule).where(CasbinRule.ptype == 'p'))
        ).all()
        extra = [_row(r) for r in stored if not catalog_owns_policy(catalog, _row(r))]
        _policies = list(dict.fromkeys([*catalog_policies(catalog), *extra]))
    return _policies


@db_context_session
async def can(
    user_id: object,
    domains: Sequence[str],
    resource: str,
    action: str,
    *,
    session: DBAsyncScopedSession | None = None,
) -> bool:
    """Allowed when a role granted to ``user_id`` in ``domains`` (most specific first, see
    ``resource_domains``) permits ``resource``/``action``."""
    assert session is not None  # injected by db_context_session
    if not domains:
        return False
    rows = await session.execute(
        select(CasbinRule.v1, CasbinRule.v2).where(
            CasbinRule.ptype == 'g',
            CasbinRule.v0 == str(user_id),
            CasbinRule.v2.in_(list(domains)),
        )
    )
    grants = [(role, domain) for role, domain in rows.all() if role and domain]
    if not grants:
        return False
    return evaluate(grants, await _load_policies(session), domains, resource, action)


@db_context_session(auto_commit=True)
async def grant(
    user_id: object,
    role: str,
    domain: str,
    *,
    session: DBAsyncScopedSession | None = None,
) -> None:
    """Idempotent ``g, <user_id>, <role>, <domain>`` (e.g. ``project_admin`` on ``project:<id>``)."""
    assert session is not None  # injected by db_context_session
    exists = await session.scalar(
        select(CasbinRule.id).where(
            CasbinRule.ptype == 'g',
            CasbinRule.v0 == str(user_id),
            CasbinRule.v1 == role,
            CasbinRule.v2 == domain,
        )
    )
    if exists is None:
        session.add(CasbinRule(ptype='g', v0=str(user_id), v1=role, v2=domain))
        await session.flush()


@db_context_session(auto_commit=True)
async def revoke(
    user_id: object,
    role: str,
    domain: str,
    *,
    session: DBAsyncScopedSession | None = None,
) -> None:
    assert session is not None  # injected by db_context_session
    await session.execute(
        delete(CasbinRule).where(
            CasbinRule.ptype == 'g',
            CasbinRule.v0 == str(user_id),
            CasbinRule.v1 == role,
            CasbinRule.v2 == domain,
        )
    )
