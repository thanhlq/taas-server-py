"""RBAC catalogs and the domain RBAC decision, mirror of ``@taas/iam`` ``rbac.ts`` + ``@taas/iam-db``.

Pure functions (no I/O): load a JSON catalog, turn it into casbin ``p`` rows, decide ownership of a
stored row, validate, and evaluate ``can`` with the same casbin model as Node::

    m = g(r.sub, p.sub, r.dom) && keyMatch(r.dom, p.dom)
        && (p.obj == "*" || r.obj == p.obj) && (p.act == "*" || r.act == p.act)

Specs: taas-specs/iam/specs/authorization-rbac-spec.md (decision), app-roles-spec.md (roles per app).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).parent / 'data'

type PolicyRow = tuple[str, str, str, str]
"""``(role, domain pattern, resource, action)``."""


class ProjectRoles(StrEnum):
    """Business roles granted on ``project:<id>`` (``ews-rbac.json``)."""

    PROJECT_ADMIN = 'project_admin'
    PROJECT_MEMBER = 'project_member'
    PROJECT_VIEWER = 'project_viewer'


class EwsResources(StrEnum):
    """Resources the EWS code checks; every value exists in ``ews-rbac.json`` (unit-tested)."""

    PROJECT = 'ppm.project'
    PROJECT_MEMBER = 'ppm.project_member'
    WORKFLOW = 'ppm.workflow'
    TASK = 'ppm.task'
    TASK_ACTIVITY = 'ppm.task_activity'
    CRM_ACCOUNT = 'crm.account'


@dataclass(frozen=True)
class RbacRole:
    key: str
    scope: str
    permissions: tuple[str, ...]
    name: str | None = None
    extends: str | None = None


@dataclass(frozen=True)
class RbacCatalog:
    catalog: str
    version: int
    namespaces: tuple[str, ...]
    resources: dict[str, tuple[str, ...]]
    roles: tuple[RbacRole, ...]
    retired_resources: tuple[str, ...] = field(default=())

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> RbacCatalog:
        return RbacCatalog(
            catalog=raw['catalog'],
            version=int(raw['version']),
            namespaces=tuple(raw['namespaces']),
            resources={r['key']: tuple(r['actions']) for r in raw['resources']},
            roles=tuple(
                RbacRole(
                    key=r['key'],
                    scope=r['scope'],
                    permissions=tuple(r['permissions']),
                    name=r.get('name'),
                    extends=r.get('extends'),
                )
                for r in raw['roles']
            ),
            retired_resources=tuple(raw.get('retiredResources', ())),
        )

    @staticmethod
    def load(path: Path) -> RbacCatalog:
        return RbacCatalog.from_dict(json.loads(path.read_text(encoding='utf-8')))


@lru_cache(maxsize=1)
def ews_catalog() -> RbacCatalog:
    """The business catalog shipped with the EWS API (``data/ews-rbac.json``)."""
    return RbacCatalog.load(_DATA / 'ews-rbac.json')


def _split(permission: str) -> tuple[str, str]:
    resource, sep, action = permission.rpartition(':')
    return (resource, action or '*') if sep and resource else (permission, '*')


def _namespace(resource: str) -> str:
    return '*' if resource == '*' else resource.split('.', 1)[0]


def catalog_policies(catalog: RbacCatalog) -> list[PolicyRow]:
    """The ``p`` rows a catalog defines (deduplicated, in catalog order)."""
    rows: dict[PolicyRow, None] = {}
    for role in catalog.roles:
        for permission in role.permissions:
            resource, action = _split(permission)
            rows[(role.key, f'{role.scope}:*', resource, action)] = None
    return list(rows)


def catalog_owns_policy(catalog: RbacCatalog, row: Sequence[str | None]) -> bool:
    """A stored ``p`` row is managed by the catalog: one of its roles on one of its (or retired) resources."""
    role, _, resource = (row[0] or ''), row[1], (row[2] or '')
    if not role or not resource or role not in {r.key for r in catalog.roles}:
        return False
    return (
        _namespace(resource) in catalog.namespaces
        or resource in catalog.retired_resources
    )


def validate_catalog(catalog: RbacCatalog) -> list[str]:
    """Integrity problems of a catalog (empty = valid)."""
    errors: list[str] = []
    seen = [f'{r.key}@{r.scope}' for r in catalog.roles]
    if len(set(seen)) != len(seen):
        errors.append('duplicate role')
    for key in catalog.resources:
        if _namespace(key) not in catalog.namespaces:
            errors.append(
                f'resource {key} is outside the namespaces {", ".join(catalog.namespaces)}'
            )
    for role in catalog.roles:
        for permission in role.permissions:
            resource, action = _split(permission)
            if resource == '*':
                continue
            actions = catalog.resources.get(resource)
            if actions is None:
                errors.append(f'role {role.key}: unknown resource {resource}')
            elif action != '*' and action not in actions:
                errors.append(f'role {role.key}: unknown action {resource}:{action}')
    return errors


def key_match(key: str, pattern: str) -> bool:
    """casbin ``keyMatch``: ``*`` matches the rest of the key (``project:*`` matches ``project:42``)."""
    i = pattern.find('*')
    if i == -1:
        return key == pattern
    return key[:i] == pattern[:i] if len(key) > i else key == pattern[:i]


def evaluate(
    grants: Iterable[tuple[str, str]],
    policies: Iterable[PolicyRow],
    domains: Sequence[str],
    resource: str,
    action: str,
) -> bool:
    """``True`` when a role granted in one of ``domains`` (``(role, domain)`` grants of the user) allows
    ``resource``/``action``. ``domains`` = most specific first, e.g. project -> org -> parent -> tenant."""
    granted = [(role, domain) for role, domain in grants if domain in domains]
    if not granted:
        return False
    rules = list(policies)
    for role, domain in granted:
        for p_role, p_dom, p_obj, p_act in rules:
            if (
                p_role == role
                and key_match(domain, p_dom)
                and (p_obj == '*' or p_obj == resource)
                and (p_act == '*' or p_act == action)
            ):
                return True
    return False


def resource_domains(
    *, tenant_id: object, org_path: str | None = None, project_id: object | None = None
) -> list[str]:
    """RBAC domains of a business object, most specific first: ``project:<id>``, its organization and
    ancestors (from the materialized ``path`` ``/<root>/<child>/``), then ``tenant:<id>``."""
    domains = [f'project:{project_id}'] if project_id else []
    if org_path:
        domains += [f'org:{o}' for o in reversed([o for o in org_path.split('/') if o])]
    domains.append(f'tenant:{tenant_id}')
    return domains
