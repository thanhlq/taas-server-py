"""PPM V2 transition rules and team workflows on the local database (taas-specs/ppm/project/project-workflow
§"Transition rules & team workflows", Ppm-0201…0205). Development sign-in (all permissions)."""

from __future__ import annotations

import uuid

import httpx

P = '/api/v1/projects'
T = '/api/v1/tasks'


async def _project(client: httpx.AsyncClient) -> tuple[str, str, dict[str, str]]:
    res = await client.post(
        f'{P}/', json={'name': f'Rules {uuid.uuid4().hex[:6]}', 'code': 'RU'}
    )
    assert res.status_code == 201, res.text
    pid = res.json()['id']
    workflow = (await client.get(f'{P}/{pid}/workflows')).json()[0]
    by_type: dict[str, str] = {}
    for stage in workflow['stages']:
        by_type.setdefault(stage['stage_type'], stage['id'])
    return pid, workflow['id'], by_type


async def _stage(
    client: httpx.AsyncClient, pid: str, wid: str, sid: str, **body
) -> dict:
    res = await client.patch(f'{P}/{pid}/workflows/{wid}/stages/{sid}', json=body)
    assert res.status_code == 200, res.text
    return next(s for s in res.json()['stages'] if s['id'] == sid)


async def test_transition_rules_requirements_and_auto_assign(client: httpx.AsyncClient):
    pid, wid, st = await _project(client)
    first, active, done = (
        st['new' if 'new' in st else 'todo'],
        st['in_progress'],
        st['done'],
    )
    rules = await _stage(client, pid, wid, first, allowed_next_stage_ids=[active])
    assert rules['allowed_next_stage_ids'] == [active]
    bad = await client.patch(
        f'{P}/{pid}/workflows/{wid}/stages/{first}',
        json={'allowed_next_stage_ids': [first]},
    )
    assert bad.status_code == 400

    item = (
        await client.post(
            f'{T}/', json={'project_id': pid, 'name': 'Contract', 'stage_id': first}
        )
    ).json()
    # Ppm-0201: not an allowed next stage (complete included: no done stage reachable)
    res = await client.patch(f'{T}/{item["id"]}', json={'stage_id': done})
    assert (
        res.status_code == 409
        and res.json()['extra']['code'] == 'transition_not_allowed'
    )
    assert res.json()['extra']['allowed'] == [active]
    res = await client.post(f'{T}/{item["id"]}/complete')
    assert (
        res.status_code == 409
        and res.json()['extra']['code'] == 'transition_not_allowed'
    )
    assert (
        await client.patch(f'{T}/{item["id"]}', json={'stage_id': active})
    ).status_code == 200

    # Ppm-0202: entry requirements; one PATCH may bring them with the move
    await _stage(client, pid, wid, done, require_assignee=True, require_due_date=True)
    res = await client.patch(f'{T}/{item["id"]}', json={'stage_id': done})
    assert res.status_code == 409 and res.json()['extra']['missing'] == [
        'assignee',
        'due_date',
    ]
    res = await client.patch(
        f'{T}/{item["id"]}',
        json={
            'stage_id': done,
            'user_id': 'anna@example.com',
            'due_date': '2026-10-20T00:00:00',
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()['completed_at'] is not None
    # reopen is free (back to the previous stage)
    assert (await client.post(f'{T}/{item["id"]}/reopen')).json()['stage_id'] == active

    # Ppm-0203: default assignee on entry
    review = st.get('review') or st.get('testing') or first
    await _stage(
        client,
        pid,
        wid,
        review,
        auto_assign=True,
        default_assignee_id='lead@example.com',
    )
    other = (
        await client.post(
            f'{T}/', json={'project_id': pid, 'name': 'Audit', 'stage_id': active}
        )
    ).json()
    res = await client.patch(f'{T}/{other["id"]}', json={'stage_id': review})
    if review != first:
        assert res.status_code == 200, res.text
        assert res.json()['user_id'] == 'lead@example.com'
    cleared = await _stage(client, pid, wid, first, clear=['allowed_next_stage_ids'])
    assert cleared.get('allowed_next_stage_ids', []) == []


async def test_team_workflows(client: httpx.AsyncClient, test_org, sql):
    mine, other = uuid.uuid7(), uuid.uuid7()
    for team_id, name in ((mine, 'Field crew'), (other, 'Back office')):
        await sql(
            'insert into taas_team (id, name, status, team_type, slug, created_at, updated_at, tenant_id, '
            "organization_id) values (:id, :name, 'ACTIVE', '1', :slug, now(), now(), :t, :o)",
            {
                'id': team_id,
                'name': name,
                'slug': f'team-{team_id.hex[-12:]}',
                't': test_org.tenant_id,
                'o': test_org.organization_id,
            },
        )
    await sql(
        'insert into taas_team_member (id, user_id, team_id, role, is_owner, created_at, updated_at) '
        "values (:id, :u, :t, 'MEMBER', false, now(), now())",
        {'id': uuid.uuid7(), 'u': test_org.user_id, 't': mine},
    )
    teams = {t['name']: t for t in (await client.get('/api/v1/ppm/teams')).json()}
    assert teams['Field crew']['is_member'] and teams['Field crew']['member_count'] == 1
    assert not teams['Back office'].get('is_member')

    pid, _, _ = await _project(client)
    res = await client.post(
        f'{P}/{pid}/workflows', json={'name': 'Crew board', 'privacy': 'team'}
    )
    assert res.status_code == 400
    crew = await client.post(
        f'{P}/{pid}/workflows',
        json={'name': 'Crew board', 'privacy': 'team', 'team_id': str(mine)},
    )
    assert crew.status_code == 201, crew.text
    office = await client.post(
        f'{P}/{pid}/workflows',
        json={'name': 'Office board', 'privacy': 'team', 'team_id': str(other)},
    )
    assert office.json()['team_id'] == str(other)
    # the caller (a project member through dev sign-in, not its responsible user) sees its team's board only
    await client.patch(f'{P}/{pid}', json={'user_id': 'someone@example.com'})
    listed = {w['name']: w for w in (await client.get(f'{P}/{pid}/workflows')).json()}
    assert listed['Crew board'].get('viewer_member') is True
    assert 'Office board' not in listed
