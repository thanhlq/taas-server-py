"""Shared building blocks of the object apps: ``ews.access.ObjectAccess`` (pure parts) and the
materialized-path tree helpers of ``ews.shared``."""

import uuid

import pytest
from ews.access import ObjectAccess, object_roles, role_permissions
from ews.security import RequestScope
from ews.security._directory import DirectoryOrganization
from ews.shared import ancestor_ids, check_move, child_path, depth_of
from foundation.exceptions import ClientException

DRIVE = ObjectAccess('drive', 'files.drive', 'files', default_role='drive_editor')


def _scope() -> RequestScope:
    root, child = uuid.uuid4(), uuid.uuid4()
    org = DirectoryOrganization(
        id=child,
        tenant_id=uuid.uuid4(),
        slug='c',
        name='C',
        path=f'/{root}/{child}/',
        depth=1,
    )
    return RequestScope(
        user_id=uuid.uuid4(),
        email=None,
        name=None,
        tenant_id=org.tenant_id,
        organization=org,
    )


def test_roles_of_a_kind_come_from_the_catalog_highest_first():
    assert DRIVE.roles == (
        'drive_manager',
        'drive_editor',
        'drive_commenter',
        'drive_viewer',
    )
    assert (
        DRIVE.rank('drive_manager')
        > DRIVE.rank('drive_viewer')
        > DRIVE.rank('org_admin')
        == 0
    )
    assert [r.key for r in object_roles(DRIVE) if r.default] == ['drive_editor']
    assert all(r.description for r in object_roles(DRIVE))


def test_role_permissions_expand_wildcards():
    assert 'files.item:restore' in role_permissions('drive_manager')
    assert 'files.item:restore' in role_permissions('drive_editor')
    assert 'files.member:manage' not in role_permissions('drive_editor')
    assert role_permissions('kb_space_viewer') >= {'kb.space:read', 'kb.page:read'}
    assert 'kb.page:update' not in role_permissions('kb_space_viewer')


def test_domains_go_from_the_object_to_the_tenant():
    scope = _scope()
    domains = DRIVE.domains(scope, 'D')
    assert domains[0] == 'drive:D'
    assert domains[1] == f'org:{scope.organization_id}'
    assert domains[-1] == f'tenant:{scope.tenant_id}'
    assert DRIVE.domains(scope, 'D', org_path='/R/') == [
        'drive:D',
        'org:R',
        f'tenant:{scope.tenant_id}',
    ]


def test_member_roles_are_validated():
    assert DRIVE.require_role('drive_viewer') == 'drive_viewer'
    with pytest.raises(ClientException):
        DRIVE.require_role('org_admin')


def test_tree_paths():
    a, b = uuid.uuid4(), uuid.uuid4()
    pa = child_path(None, a)
    pb = child_path(pa, b)
    assert pa == f'/{a}/' and pb == f'/{a}/{b}/'
    assert depth_of(pa) == 0 and depth_of(pb) == 1
    assert ancestor_ids(pb) == [a]


def test_tree_moves_are_checked():
    a, b = uuid.uuid4(), uuid.uuid4()
    pa = child_path(None, a)
    pb = child_path(pa, b)
    with pytest.raises(ClientException):
        check_move(pa, pb)  # into its own subtree
    with pytest.raises(ClientException):
        check_move(pb, pa, max_depth=2, subtree_height=1)
    check_move(pb, None, max_depth=2, subtree_height=1)
