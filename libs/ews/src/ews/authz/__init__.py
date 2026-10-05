"""Business RBAC of the EWS apps: roles / permissions catalog (``data/ews-rbac.json``), its start-up
sync into ``taas_casbin_rule`` and the ``can`` decision. Specs: taas-specs/iam/specs/app-roles-spec.md, authorization-rbac-spec.md."""

from ._catalog import (
    EwsResources,
    PolicyRow,
    ProjectRoles,
    RbacCatalog,
    RbacRole,
    catalog_owns_policy,
    catalog_policies,
    evaluate,
    ews_catalog,
    key_match,
    resource_domains,
    validate_catalog,
)
from ._store import SyncResult, can, grant, revoke, sync_catalog

__all__ = [
    'EwsResources',
    'PolicyRow',
    'ProjectRoles',
    'RbacCatalog',
    'RbacRole',
    'SyncResult',
    'can',
    'catalog_owns_policy',
    'catalog_policies',
    'evaluate',
    'ews_catalog',
    'grant',
    'key_match',
    'resource_domains',
    'revoke',
    'sync_catalog',
    'validate_catalog',
]
