"""RBAC catalogs and the domain RBAC decision, mirror of ``@taas/iam`` ``rbac.ts`` + ``@taas/iam-db``.

Pure functions (no I/O): load a JSON catalog, turn it into casbin ``p`` rows, decide ownership of a
stored row, validate, merge the policies of the built-in catalogs, and evaluate ``can`` with the same
casbin model as Node::

    m = g(r.sub, p.sub, r.dom) && keyMatch(r.dom, p.dom)
        && (p.obj == "*" || r.obj == p.obj) && (p.act == "*" || r.act == p.act)

Both runtimes ship both catalogs (``data/ews-rbac.json`` owned here, ``data/iam-rbac.json`` copied from
taas-server-js) and run the same decision vectors (``data/rbac-cases.json``, owned by taas-server-js):
``python3 taas-tools/rbac-catalogs/sync_rbac_catalogs.py`` copies them.

Specs: taas-specs/iam/specs/authorization-rbac-spec.md (decision, §5 parity), app-roles-spec.md (roles per app).
"""

from __future__ import annotations

import json
import re
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


class SiteRoles(StrEnum):
    """Site builder roles granted on ``site:<id>`` (``ews-rbac.json``), highest first."""

    SITE_ADMIN = 'site_admin'
    SITE_EDITOR = 'site_editor'
    SITE_AUTHOR = 'site_author'
    SITE_VIEWER = 'site_viewer'


class EwsResources(StrEnum):
    """Resources the EWS code checks; every value exists in ``ews-rbac.json`` (unit-tested)."""

    PROJECT = 'ppm.project'
    PROJECT_MEMBER = 'ppm.project_member'
    WORKFLOW = 'ppm.workflow'
    TASK = 'ppm.task'
    TASK_ACTIVITY = 'ppm.task_activity'
    PPM_SETTINGS = 'ppm.settings'
    ITEM_TYPE = 'ppm.item_type'
    CUSTOM_FIELD = 'ppm.custom_field'
    CHECKLIST_TEMPLATE = 'ppm.checklist_template'
    PROJECT_TEMPLATE = 'ppm.template'
    SCHEDULE = 'ppm.schedule'
    APPROVAL = 'ppm.approval'
    FORM = 'ppm.form'
    REQUEST = 'ppm.request'
    TIMESHEET = 'ppm.timesheet'
    TIME_ENTRY = 'ppm.time_entry'
    HEALTH = 'ppm.health'
    HEALTH_POLICY = 'ppm.health_policy'
    AUTOMATION = 'ppm.automation'
    DASHBOARD = 'ppm.dashboard'
    CRM_ACCOUNT = 'crm.account'
    SITE = 'sites.site'
    SITE_THEME = 'sites.theme'
    SITE_DOMAIN = 'sites.domain'
    SITE_PAGE = 'sites.page'
    SITE_MENU = 'sites.menu'
    SITE_REDIRECT = 'sites.redirect'
    SITE_SEO = 'sites.seo'
    SITE_MEMBER = 'sites.member'
    SITE_SUBMISSION = 'sites.submission'
    SITE_AI = 'sites.ai'
    MEDIA_ASSET = 'media.asset'
    MEDIA_FOLDER = 'media.folder'
    FILES_DRIVE = 'files.drive'
    FILES_ITEM = 'files.item'
    FILES_MEMBER = 'files.member'
    KB_SPACE = 'kb.space'
    KB_SPACE_MEMBER = 'kb.space_member'
    KB_PAGE = 'kb.page'
    KB_LINK = 'kb.link'
    KB_AI = 'kb.ai'
    BLOG_BLOG = 'blog.blog'
    BLOG_MEMBER = 'blog.member'
    BLOG_POST = 'blog.post'
    BLOG_TAXONOMY = 'blog.taxonomy'
    BLOG_AI = 'blog.ai'


@dataclass(frozen=True)
class RbacRole:
    key: str
    scope: str
    permissions: tuple[str, ...]
    name: str | None = None
    extends: str | None = None
    description: str | None = None


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
                    description=r.get('description'),
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


@lru_cache(maxsize=1)
def iam_catalog() -> RbacCatalog:
    """The IAM catalog (copy of taas-server-js ``@taas/iam`` ``rbac/iam-rbac.json``; the IAM syncs it)."""
    return RbacCatalog.load(_DATA / 'iam-rbac.json')


def builtin_catalogs() -> tuple[RbacCatalog, ...]:
    """Every catalog a runtime evaluates (Node ``BUILTIN_RBAC_CATALOGS``)."""
    return (iam_catalog(), ews_catalog())


# Role keys: ``tenant_admin``, ``drive_editor``. Scopes (domain kinds): ``tenant``, ``org``, ``kb-space``.
_ROLE_KEY = re.compile(r'^[a-z][a-z0-9_]*$')
_ROLE_SCOPE = re.compile(r'^[a-z][a-z-]*$')


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
        if not _ROLE_KEY.match(role.key):
            errors.append(f'role {role.key}: invalid key')
        if not _ROLE_SCOPE.match(role.scope):
            errors.append(f'role {role.key}: invalid scope {role.scope}')
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


def effective_policies(
    own: RbacCatalog,
    stored: Iterable[Sequence[str | None]],
    catalogs: Sequence[RbacCatalog] | None = None,
) -> list[PolicyRow]:
    """Policies a runtime evaluates (Node ``effectivePolicies``): its own catalog from JSON (the truth),
    every other built-in catalog from the stored rows its owner synced — or the shipped copy while the
    owner has not synced yet — plus the stored custom rows."""
    catalogs = builtin_catalogs() if catalogs is None else tuple(catalogs)
    rows_in: list[PolicyRow] = [
        (row[0] or '', row[1] or '', row[2] or '', row[3] or '') for row in stored
    ]
    rows: dict[PolicyRow, None] = dict.fromkeys(catalog_policies(own))
    for catalog in catalogs:
        if catalog.catalog == own.catalog:
            continue
        synced = [
            r
            for r in rows_in
            if catalog_owns_policy(catalog, r) and not catalog_owns_policy(own, r)
        ]
        rows.update(dict.fromkeys(synced or catalog_policies(catalog)))
    custom = [
        r for r in rows_in if not any(catalog_owns_policy(c, r) for c in catalogs)
    ]
    rows.update(dict.fromkeys(custom))
    return list(rows)


def resource_domains(
    *,
    tenant_id: object,
    org_path: str | None = None,
    project_id: object | None = None,
    site_id: object | None = None,
    objects: Sequence[tuple[str, object]] = (),
) -> list[str]:
    """RBAC domains of a business object, most specific first: the object(s) (``project:<id>``,
    ``site:<id>``, ``objects`` such as ``('drive', id)``), its organization and ancestors (from the
    materialized ``path`` ``/<root>/<child>/``), then ``tenant:<id>``. Node ``resourceDomains``."""
    domains = [f'{kind}:{oid}' for kind, oid in objects]
    if project_id:
        domains.insert(0, f'project:{project_id}')
    if site_id:
        domains.append(f'site:{site_id}')
    if org_path:
        domains += [f'org:{o}' for o in reversed([o for o in org_path.split('/') if o])]
    domains.append(f'tenant:{tenant_id}')
    return domains
