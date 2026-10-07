"""PPM + CRM API: authentication, tenant / organization scoping, permissions (taas-specs/ppm/ppm-app-spec.md
Ppm-0001 / Ppm-0002, taas-specs/crm/crm-app-spec.md). Development mode unless a test switches to ``iam``."""

from __future__ import annotations

import uuid

import base64
import json

import httpx


def dev_cookie(email: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({'email': email, 'name': 'Tester'}).encode()).rstrip(b'=').decode()


async def _sub(test_org) -> str:
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        query = text('select directory_id from taas_user_account where id = :id')
        return (await conn.execute(query, {'id': test_org.user_id})).scalar_one()


async def _project(client: httpx.AsyncClient, name: str = 'Scoped project') -> dict:
    res = await client.post('/api/v1/projects/', json={'name': name, 'code': 'SCP'})
    assert res.status_code == 201, res.text
    return res.json()


async def test_signed_out_and_cross_site_writes_are_rejected(app, test_org):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as anon:
        assert (await anon.get('/api/v1/projects/')).status_code == 401
        assert (await anon.get('/api/v1/crm/accounts/')).status_code == 401
        assert (await anon.get('/api/v1/projects/statuses')).status_code == 401
    cookies = {'taas_dev_session': dev_cookie(test_org.email)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', cookies=cookies) as c:
        # Cookie-authenticated write without / with a foreign Origin → 403 (CSRF); reads are fine.
        assert (await c.post('/api/v1/projects/', json={'name': 'x'})).status_code == 403
        bad = {'Origin': 'https://evil.test'}
        assert (await c.post('/api/v1/projects/', json={'name': 'x'}, headers=bad)).status_code == 403
        assert (await c.get('/api/v1/projects/')).status_code == 200


async def test_projects_belong_to_the_url_organization(client: httpx.AsyncClient, test_org):
    project = await _project(client)
    pid = project['id']
    assert pid in [p['id'] for p in (await client.get('/api/v1/projects/')).json()['items']]

    # The child organization (by slug, as the web sends it) does not see the parent's project.
    child = {'X-Organization-Id': '', 'X-Tenant-ID': '', 'X-Organization-Slug': f'{test_org.slug}-child'}
    listed = (await client.get('/api/v1/projects/', headers=child)).json()['items']
    assert pid not in [p['id'] for p in listed]
    assert (await client.get(f'/api/v1/projects/{pid}', headers=child)).status_code == 404
    assert (await client.patch(f'/api/v1/projects/{pid}', json={'name': 'x'}, headers=child)).status_code == 404

    # The slug of the parent organization works like its id.
    by_slug = {'X-Organization-Id': '', 'X-Tenant-ID': '', 'X-Organization-Slug': test_org.slug}
    assert (await client.get(f'/api/v1/projects/{pid}', headers=by_slug)).status_code == 200

    # Malformed and unknown ids are 404, never 500.
    assert (await client.get('/api/v1/projects/not-a-uuid')).status_code == 404
    assert (await client.get(f'/api/v1/projects/{uuid.uuid4()}')).status_code == 404
    assert (await client.get('/api/v1/tasks/not-a-uuid')).status_code == 404
    assert (await client.patch(f'/api/v1/projects/{pid}/workflows/not-a-uuid', json={})).status_code == 404


async def test_tasks_stay_inside_their_project(client: httpx.AsyncClient):
    a = await _project(client, 'Project A')
    b = await _project(client, 'Project B')
    task_list = (await client.post(f"/api/v1/projects/{b['id']}/task-lists", json={'name': 'B list'})).json()
    # A task of A cannot reference B's task list (or a malformed id).
    res = await client.post('/api/v1/tasks/', json={'project_id': a['id'], 'name': 't', 'task_list_id': task_list['id']})
    assert res.status_code == 400
    res = await client.post('/api/v1/tasks/', json={'project_id': a['id'], 'name': 't', 'iteration_id': 'bad'})
    assert res.status_code == 400
    task = (await client.post('/api/v1/tasks/', json={'project_id': a['id'], 'name': 'ok'})).json()
    res = await client.patch(f"/api/v1/tasks/{task['id']}", json={'task_list_id': task_list['id']})
    assert res.status_code == 400
    # B's task list is not reachable through A's path.
    assert (await client.patch(f"/api/v1/projects/{a['id']}/task-lists/{task_list['id']}", json={'name': 'x'})).status_code == 404


async def test_comment_author_from_session_and_soft_deletes(client: httpx.AsyncClient, test_org, sql):
    project = await _project(client, 'Activity')
    task = (await client.post('/api/v1/tasks/', json={'project_id': project['id'], 'name': 'Log me'})).json()
    comment = await client.post(f"/api/v1/tasks/{task['id']}/comments", json={'text': 'hi', 'user_id': 'spoof@x.test'})
    assert comment.status_code == 201 and comment.json()['user_id'] == test_org.email

    log = await client.post(f"/api/v1/tasks/{task['id']}/timelogs", json={'minutes': 30})
    assert log.status_code == 201 and log.json()['user_id'] == test_org.email
    assert (await client.get(f"/api/v1/tasks/{task['id']}")).json()['actual_minutes'] == 30
    assert (await client.delete(f"/api/v1/tasks/{task['id']}/timelogs/{log.json()['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/tasks/{task['id']}/timelogs")).json() == []
    assert (await client.get(f"/api/v1/tasks/{task['id']}")).json().get('actual_minutes', 0) == 0

    # Task delete is soft: gone from the API, still in the database with its time log.
    assert (await client.delete(f"/api/v1/tasks/{task['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/tasks/{task['id']}")).status_code == 404
    listed = (await client.get('/api/v1/tasks/', params={'project_id': project['id']})).json()['items']
    assert task['id'] not in [t['id'] for t in listed]
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().connect() as conn:
        kept = (await conn.execute(text('select count(*) from taas_timelogs where task_id = :t'), {'t': task['id']})).scalar_one()
    assert kept == 1

    # Project delete is soft as well.
    assert (await client.delete(f"/api/v1/projects/{project['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/projects/{project['id']}")).status_code == 404


async def test_crm_accounts_are_scoped(client: httpx.AsyncClient, test_org):
    created = await client.post('/api/v1/crm/accounts/', json={'name': 'Scoped Ltd', 'org_id': 'ignored'})
    assert created.status_code == 201, created.text
    aid = created.json()['id']
    assert aid in [a['id'] for a in (await client.get('/api/v1/crm/accounts/')).json()['items']]
    child = {'X-Organization-Id': str(test_org.child_organization_id)}
    assert aid not in [a['id'] for a in (await client.get('/api/v1/crm/accounts/', headers=child)).json()['items']]
    assert (await client.get(f'/api/v1/crm/accounts/{aid}', headers=child)).status_code == 404
    assert (await client.get('/api/v1/crm/accounts/not-a-uuid')).status_code == 404


async def test_ppm_and_crm_permissions_in_iam_mode(app, test_org, sql):
    """org_member: creates projects (becomes their Project Admin), sees only projects with a role, CRM without
    delete; org_admin sees every project of the organization."""
    from ews.authz import grant, revoke_domain
    from ews.security import EwsAuthSettings, SessionVerifierT, VerifiedSession, configure_security

    class Verifier(SessionVerifierT):
        async def verify(self, headers):
            auth = headers.get('authorization', '')
            return VerifiedSession(sub=auth.split()[1]) if auth else None

    sub = await _sub(test_org)
    await sql(
        "insert into taas_organization_members (id, user_id, organization_id, tenant_id, role, is_owner, created_at, "
        "updated_at, joined_via) values (:id, :u, :o, :t, 'org_member', false, now(), now(), 'admin') on conflict do nothing",
        {'id': uuid.uuid4(), 'u': test_org.user_id, 'o': test_org.organization_id, 't': test_org.tenant_id},
    )
    org = f'org:{test_org.organization_id}'
    await grant(test_org.user_id, 'org_admin', org)
    configure_security(settings=EwsAuthSettings(mode='iam'), verifier=Verifier())
    headers = {'Authorization': f'Bearer {sub}', 'X-Organization-Slug': test_org.slug}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as c:
            # As org admin: a project made by "someone else" (no project role for this user afterwards).
            foreign = (await c.post('/api/v1/projects/', json={'name': 'Admin only'})).json()
            await revoke_domain(f"project:{foreign['id']}", user_id=test_org.user_id)
            assert foreign['id'] in [p['id'] for p in (await c.get('/api/v1/projects/')).json()['items']]

            # Now a plain member.
            await revoke_domain(org, user_id=test_org.user_id)
            await grant(test_org.user_id, 'org_member', org)
            mine = await c.post('/api/v1/projects/', json={'name': 'Mine'})
            assert mine.status_code == 201, mine.text
            listed = [p['id'] for p in (await c.get('/api/v1/projects/')).json()['items']]
            assert mine.json()['id'] in listed and foreign['id'] not in listed
            assert (await c.get(f"/api/v1/projects/{foreign['id']}")).status_code == 404
            assert (await c.patch(f"/api/v1/projects/{mine.json()['id']}", json={'name': 'Mine 2'})).status_code == 200

            # A viewer role reads but cannot write.
            await grant(test_org.user_id, 'project_viewer', f"project:{foreign['id']}")
            assert (await c.get(f"/api/v1/projects/{foreign['id']}")).status_code == 200
            assert (await c.patch(f"/api/v1/projects/{foreign['id']}", json={'name': 'x'})).status_code == 403
            assert (await c.post('/api/v1/tasks/', json={'project_id': foreign['id'], 'name': 't'})).status_code == 403

            # CRM: members create / read, but do not delete.
            account = await c.post('/api/v1/crm/accounts/', json={'name': 'Member Co'})
            assert account.status_code == 201, account.text
            assert (await c.delete(f"/api/v1/crm/accounts/{account.json()['id']}")).status_code == 403

            # Foreign organization slug → 404.
            assert (await c.get('/api/v1/projects/', headers={'X-Organization-Slug': 'no-such-org-xyz'})).status_code == 404
    finally:
        configure_security(settings=EwsAuthSettings(mode='dev', dev_organization_id=str(test_org.organization_id)))
        await revoke_domain(org, user_id=test_org.user_id)
