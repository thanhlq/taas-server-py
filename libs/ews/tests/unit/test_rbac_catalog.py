"""Business RBAC catalog (``ews-rbac.json``) and the casbin-equivalent decision (parity with Node)."""

from pathlib import Path

import pytest
from ews.authz import (
    EwsResources,
    ProjectRoles,
    RbacCatalog,
    catalog_owns_policy,
    catalog_policies,
    evaluate,
    ews_catalog,
    key_match,
    resource_domains,
    validate_catalog,
)

# The IAM catalog of taas-server-js (same taas-all checkout); parity tests skip without it.
_IAM_JSON = (
    Path(__file__).resolve().parents[5]
    / 'taas-server-js/packages/iam/src/rbac/iam-rbac.json'
)

# Built-in IAM rows (subset of iam-rbac.json) for the decision tests below.
_IAM_ROWS = [
    ('tenant_admin', 'tenant:*', '*', '*'),
    ('org_admin', 'org:*', 'iam.member', '*'),
]


def _policies():
    return [*_IAM_ROWS, *catalog_policies(ews_catalog())]


def test_catalog_is_valid():
    assert validate_catalog(ews_catalog()) == []


def test_resources_and_roles_exist_in_the_catalog():
    catalog = ews_catalog()
    assert {r.value for r in EwsResources} <= set(catalog.resources)
    assert {r.value for r in ProjectRoles} <= {
        r.key for r in catalog.roles if r.scope == 'project'
    }


def test_extended_roles_are_iam_roles():
    extended = {r.key for r in ews_catalog().roles if r.extends}
    assert extended == {'org_admin', 'org_member'}
    assert all(r.extends == 'iam' for r in ews_catalog().roles if r.extends)


def test_catalog_owns_only_its_namespaces():
    catalog = ews_catalog()
    assert catalog_owns_policy(catalog, ('project_admin', 'project:*', 'ppm.task', '*'))
    assert catalog_owns_policy(catalog, ('org_admin', 'org:*', 'crm.account', '*'))
    # the IAM rows of the same roles belong to the IAM catalog
    assert not catalog_owns_policy(catalog, ('org_admin', 'org:*', 'iam.member', '*'))
    assert not catalog_owns_policy(catalog, ('tenant_admin', 'tenant:*', '*', '*'))


def test_key_match_like_casbin():
    assert key_match('project:42', 'project:*')
    assert key_match('tenant:a', 'tenant:a')
    assert not key_match('org:1', 'project:*')
    assert not key_match('tenant:a', 'tenant:b')


def test_project_roles():
    doms = resource_domains(tenant_id='T', org_path='/R/S/', project_id='P')
    assert doms == ['project:P', 'org:S', 'org:R', 'tenant:T']
    admin = [('project_admin', 'project:P')]
    member = [('project_member', 'project:P')]
    viewer = [('project_viewer', 'project:P')]
    assert evaluate(admin, _policies(), doms, 'ppm.project', 'delete')
    assert evaluate(member, _policies(), doms, 'ppm.task', 'update')
    assert not evaluate(member, _policies(), doms, 'ppm.task', 'delete')
    assert not evaluate(member, _policies(), doms, 'ppm.project', 'update')
    assert evaluate(viewer, _policies(), doms, 'ppm.task', 'read')
    assert not evaluate(viewer, _policies(), doms, 'ppm.task', 'create')


def test_a_project_role_does_not_leak_to_other_projects():
    other = resource_domains(tenant_id='T', org_path='/R/', project_id='Q')
    assert not evaluate(
        [('project_admin', 'project:P')], _policies(), other, 'ppm.task', 'read'
    )


def test_organization_and_tenant_roles_flow_down():
    doms = resource_domains(tenant_id='T', org_path='/R/S/', project_id='P')
    assert evaluate(
        [('org_admin', 'org:R')], _policies(), doms, 'ppm.project', 'delete'
    )
    assert evaluate(
        [('tenant_admin', 'tenant:T')], _policies(), doms, 'ppm.task', 'delete'
    )
    assert evaluate(
        [('org_member', 'org:S')], _policies(), doms, 'crm.account', 'update'
    )
    assert not evaluate(
        [('org_member', 'org:S')], _policies(), doms, 'ppm.task', 'read'
    )
    # roles never cross tenants or domain kinds
    assert not evaluate(
        [('tenant_admin', 'tenant:X')], _policies(), doms, 'ppm.task', 'read'
    )
    assert not evaluate(
        [('org_admin', 'tenant:T')], _policies(), doms, 'ppm.task', 'read'
    )


@pytest.mark.skipif(
    not _IAM_JSON.exists(),
    reason='taas-server-js not checked out next to taas-server-py',
)
def test_parity_with_the_iam_catalog():
    iam = RbacCatalog.load(_IAM_JSON)
    assert validate_catalog(iam) == []
    assert set(iam.namespaces).isdisjoint(ews_catalog().namespaces)
    iam_roles = {r.key for r in iam.roles}
    assert {r.key for r in ews_catalog().roles if r.extends == 'iam'} <= iam_roles
    policies = [*catalog_policies(iam), *catalog_policies(ews_catalog())]
    doms = resource_domains(tenant_id='T', org_path='/R/', project_id='P')
    assert evaluate(
        [('tenant_admin', 'tenant:T')], policies, doms, 'ppm.project', 'delete'
    )
    assert not evaluate(
        [('org_admin', 'org:R')],
        policies,
        ['org:R', 'tenant:T'],
        'iam.organization',
        'delete',
    )
