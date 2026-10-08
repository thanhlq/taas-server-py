"""One RBAC in Python and Node (taas-specs/iam/specs/authorization-rbac-spec.md §5): both catalogs, the
shared decision vectors (``data/rbac-cases.json``, also run by ``@taas/iam`` and ``@taas/iam-db``) and
the policy merge rule (``effective_policies`` = Node ``effectivePolicies``)."""

import json
from pathlib import Path

import pytest
from ews.authz import (
    builtin_catalogs,
    catalog_policies,
    effective_policies,
    evaluate,
    ews_catalog,
    iam_catalog,
    resource_domains,
    validate_catalog,
)

_DATA = Path(__file__).resolve().parents[2] / 'src/ews/authz/data'
# Owner copies in taas-server-js (same taas-all checkout); the drift tests skip without it.
_JS_RBAC = Path(__file__).resolve().parents[5] / 'taas-server-js/packages/iam/src/rbac'
_CASES = json.loads((_DATA / 'rbac-cases.json').read_text(encoding='utf-8'))['cases']
_POLICIES = [p for c in builtin_catalogs() for p in catalog_policies(c)]


def test_both_catalogs_are_valid_and_disjoint():
    assert validate_catalog(iam_catalog()) == []
    assert validate_catalog(ews_catalog()) == []
    assert set(iam_catalog().namespaces).isdisjoint(ews_catalog().namespaces)


@pytest.mark.parametrize('name', ['iam-rbac.json', 'rbac-cases.json'])
@pytest.mark.skipif(
    not _JS_RBAC.exists(),
    reason='taas-server-js not checked out next to taas-server-py',
)
def test_copies_match_their_owner(name: str):
    """Drift: run ``python3 taas-tools/rbac-catalogs/sync_rbac_catalogs.py``."""
    assert json.loads((_DATA / name).read_text(encoding='utf-8')) == json.loads(
        (_JS_RBAC / name).read_text(encoding='utf-8')
    )


@pytest.mark.skipif(
    not _JS_RBAC.exists(),
    reason='taas-server-js not checked out next to taas-server-py',
)
def test_node_ships_this_ews_catalog():
    assert json.loads(
        (_JS_RBAC / 'ews-rbac.json').read_text(encoding='utf-8')
    ) == json.loads((_DATA / 'ews-rbac.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', _CASES, ids=[c['name'] for c in _CASES])
def test_shared_vector(case: dict):
    grants = [(role, domain) for role, domain in case['grants']]
    assert (
        evaluate(grants, _POLICIES, case['domains'], case['resource'], case['action'])
        is case['allowed']
    )


def test_domains_of_any_object_kind():
    assert resource_domains(
        tenant_id='T', org_path='/R/C/', objects=[('drive', 'D')]
    ) == [
        'drive:D',
        'org:C',
        'org:R',
        'tenant:T',
    ]
    assert resource_domains(tenant_id='T', org_path='/R/', project_id='P') == [
        'project:P',
        'org:R',
        'tenant:T',
    ]


def _keys(rows):
    return {' '.join(r) for r in rows}


def test_uses_the_shipped_iam_copy_until_the_iam_has_synced():
    rows = _keys(effective_policies(ews_catalog(), []))
    assert 'tenant_admin tenant:* * *' in rows
    assert 'drive_editor drive:* files.item delete' in rows


def test_prefers_the_rows_the_iam_synced():
    rows = _keys(
        effective_policies(
            ews_catalog(), [('org_member', 'org:*', 'iam.organization', 'read')]
        )
    )
    assert 'org_member org:* iam.organization read' in rows
    assert 'tenant_admin tenant:* * *' not in rows


def test_ignores_stored_rows_of_its_own_catalog_and_keeps_custom_roles():
    stored = [
        ('org_member', 'org:*', 'crm.account', 'delete'),
        ('custom_auditor', 'tenant:*', 'iam.audit', 'read'),
    ]
    rows = _keys(effective_policies(ews_catalog(), stored))
    assert 'org_member org:* crm.account delete' not in rows
    assert 'custom_auditor tenant:* iam.audit read' in rows
