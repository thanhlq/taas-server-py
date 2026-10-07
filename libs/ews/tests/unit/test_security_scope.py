"""Request scope of the EWS apps (authorization-rbac-spec §2): identity, tenant and organization."""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest
from ews.security import (
    DirectoryMembership,
    DirectoryOrganization,
    DirectoryT,
    DirectoryUser,
    EwsAuthSettings,
    IamSessionVerifier,
    SessionVerifierT,
    VerifiedSession,
    decode_dev_session,
    resolve_scope,
)
from foundation.exceptions import ClientException, NotAuthorizedException, NotFoundException

T1, T2 = uuid.uuid4(), uuid.uuid4()
_ROOT_ID, _CHILD_ID = uuid.uuid4(), uuid.uuid4()
ROOT = DirectoryOrganization(id=_ROOT_ID, tenant_id=T1, slug='acme', name='Acme', path=f'/{_ROOT_ID}/', depth=0)
CHILD = DirectoryOrganization(id=_CHILD_ID, tenant_id=T1, slug='acme-eu', name='Acme EU', path=f'/{_ROOT_ID}/{_CHILD_ID}/', depth=1)
OTHER = DirectoryOrganization(id=uuid.uuid4(), tenant_id=T2, slug='beta', name='Beta', path='', depth=0)
USER = DirectoryUser(id=uuid.uuid4(), email='ann@acme.test', name='Ann', tenant_id=T1)


class Directory(DirectoryT):
    def __init__(self, memberships: list[DirectoryMembership]):
        self._memberships = memberships

    async def user_by_subject(self, subject):
        return USER if subject == 'sub-ann' else None

    async def user_by_email(self, email):
        return USER if email == USER.email else None

    async def memberships(self, user_id):
        return self._memberships

    async def organization(self, organization_id):
        return next((o for o in (ROOT, CHILD, OTHER) if o.id == organization_id), None)

    async def first_root_organization(self, slug=None):
        return ROOT


class Verifier(SessionVerifierT):
    async def verify(self, headers):
        return VerifiedSession(sub='sub-ann') if headers.get('cookie') == 'session=ok' else None


IAM = EwsAuthSettings(mode='iam')
SIGNED_IN = {'cookie': 'session=ok'}


async def _resolve(memberships, headers=None, settings=IAM, cookies=None):
    return await resolve_scope(settings, Directory(memberships), Verifier(), {**SIGNED_IN, **(headers or {})}, cookies or {})


async def test_default_is_the_root_organization_of_the_home_tenant():
    scope = await _resolve([DirectoryMembership(CHILD, 'org_member'), DirectoryMembership(ROOT, 'org_member')])
    assert scope.organization == ROOT and scope.tenant_id == T1
    assert scope.org_domains() == [f'org:{ROOT.id}', f'tenant:{T1}']


async def test_organization_header_and_ancestor_membership():
    scope = await _resolve([DirectoryMembership(ROOT, 'org_admin')], {'x-organization-id': str(CHILD.id)})
    assert scope.organization == CHILD
    assert scope.org_domains() == [f'org:{CHILD.id}', f'org:{ROOT.id}', f'tenant:{T1}']


async def test_foreign_organization_or_tenant_is_404_and_mismatch_400():
    member = [DirectoryMembership(ROOT, 'org_member')]
    with pytest.raises(NotFoundException):
        await _resolve(member, {'x-organization-id': str(OTHER.id)})
    with pytest.raises(NotFoundException):
        await _resolve(member, {'x-tenant-id': str(T2)})
    with pytest.raises(ClientException):
        await _resolve(member, {'x-organization-id': str(ROOT.id), 'x-tenant-id': str(T2)})
    with pytest.raises(ClientException):
        await _resolve(member, {'x-organization-id': 'not-a-uuid'})


async def test_tenant_admin_reaches_every_organization_of_its_tenant():
    scope = await _resolve([DirectoryMembership(CHILD, 'tenant_admin')], {'x-organization-id': str(ROOT.id)})
    assert scope.organization == ROOT


async def test_signed_out_is_401():
    with pytest.raises(NotAuthorizedException):
        await resolve_scope(IAM, Directory([]), Verifier(), {}, {})


async def test_development_sign_in():
    cookie = base64.urlsafe_b64encode(json.dumps({'email': USER.email, 'name': 'Ann'}).encode()).decode().rstrip('=')
    assert decode_dev_session(cookie).email == USER.email
    assert decode_dev_session('garbage') is None
    scope = await resolve_scope(EwsAuthSettings(mode='dev'), Directory([]), None, {}, {'taas_dev_session': cookie})
    assert scope.is_dev and scope.user_id == USER.id and scope.organization == ROOT


async def test_iam_session_verifier_forwards_and_caches():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get('cookie'))
        if request.headers.get('cookie') == 'sid=1':
            return httpx.Response(200, json={'sub': 'sub-ann', 'email': 'ann@acme.test'})
        return httpx.Response(401, json={'error': 'unauthorized'})

    verifier = IamSessionVerifier('http://iam', client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await verifier.verify({'cookie': 'sid=1'})).sub == 'sub-ann'
    assert (await verifier.verify({'cookie': 'sid=1'})).sub == 'sub-ann'
    assert await verifier.verify({'cookie': 'sid=2'}) is None
    assert await verifier.verify({}) is None
    assert calls == ['sid=1', 'sid=2']
