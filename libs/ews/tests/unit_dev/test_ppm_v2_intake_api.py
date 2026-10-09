"""PPM V2 intake on the local database (taas-specs/ppm/intake/intake-spec.md): forms (starter, stale version, publish
= versions, Ppm-1101…1108), internal submit with routing + idempotency (Ppm-1125, Ppm-1150), inbox / detail / triage
(Ppm-1130…1137), status mirroring (§5.4), public form + tracking (Ppm-1115, Ppm-1116, Ppm-1173), round robin, merge,
accept in place / as project, responses export (Ppm-1109). Development sign-in (all permissions)."""

from __future__ import annotations

import uuid

import httpx

P = '/api/v1/projects'
T = '/api/v1/tasks'
F = '/api/v1/ppm/forms'
Q = '/api/v1/ppm/requests'
ANSWERS = {
    'summary': 'New laptop',
    'request_type': 'issue',
    'priority': '4',
    'expected': '2026-11-30',
}


async def _project(client: httpx.AsyncClient, name: str = 'Queue') -> dict:
    res = await client.post(
        f'{P}/', json={'name': f'{name} {uuid.uuid4().hex[:6]}', 'code': 'REQ'}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _form(client: httpx.AsyncClient, project_id: str, **extra) -> dict:
    res = await client.post(
        F + '/',
        json={
            'name': 'General request',
            'project_id': project_id,
            'starter': 'general',
            **extra,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _patch(client: httpx.AsyncClient, form: dict, **fields) -> dict:
    res = await client.patch(
        f'{F}/{form["id"]}', json={'version': form['version'], **fields}
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _publish(client: httpx.AsyncClient, form_id: str) -> dict:
    res = await client.post(f'{F}/{form_id}/publish')
    assert res.status_code == 200, res.text
    return res.json()


async def _submit(
    client: httpx.AsyncClient, form_id: str, answers: dict | None = None, **headers
) -> dict:
    res = await client.post(
        f'{F}/{form_id}/submissions',
        json={'answers': answers or ANSWERS},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _public(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """A browser without a session (public pages)."""
    return httpx.AsyncClient(transport=client._transport, base_url='http://testserver')


async def test_form_lifecycle_internal_request_and_triage(client: httpx.AsyncClient):
    queue = await _project(client)
    form = await _form(client, queue['id'])
    assert form['status'] == 'draft' and form['queue_project_id'] == queue['id']
    assert len(form['draft']['fields']) == 5 and form.get('issues', []) == []
    assert form['id'] not in [
        f['id'] for f in (await client.get(f'{F}/available')).json()
    ]

    stale = await client.patch(
        f'{F}/{form["id"]}', json={'version': form['version'] + 1, 'name': 'x'}
    )
    assert stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_form'
    draft = form['draft'] | {
        'routing': [
            {
                'name': 'Urgent',
                'conditions': [{'field': 'priority', 'op': 'eq', 'value': '4'}],
                'actions': [
                    {'type': 'set_priority', 'value': 5},
                    {'type': 'add_labels', 'labels': ['urgent']},
                ],
            }
        ]
    }
    form = await _patch(client, form, draft=draft)
    published = await _publish(client, form['id'])
    assert published['status'] == 'published' and published['current_version'] == 1
    assert (await _publish(client, form['id']))[
        'current_version'
    ] == 1  # no change, no new version
    assert form['id'] in [f['id'] for f in (await client.get(f'{F}/available')).json()]
    fill = (await client.get(f'{F}/{form["id"]}/published')).json()
    assert fill['version'] == 1 and all(
        'map' not in f for f in fill['definition']['fields']
    )

    bad = await client.post(
        f'{F}/{form["id"]}/submissions', json={'answers': {'request_type': 'issue'}}
    )
    assert (
        bad.status_code == 400
        and {'field': 'summary', 'code': 'required'} in bad.json()['extra']['errors']
    )
    first = await _submit(client, form['id'], **{'Idempotency-Key': 'k-1'})
    assert first['status'] == 'submitted' and first['code'].startswith('REQ')
    assert (await _submit(client, form['id'], **{'Idempotency-Key': 'k-1'}))[
        'request_id'
    ] == first['request_id']

    item = (await client.get(f'{T}/{first["request_id"]}')).json()
    assert item['name'] == 'New laptop' and item['priority'] == 5
    assert 'urgent' in (item.get('labels') or []) and item['due_date'].startswith(
        '2026-11-30'
    )

    inbox = (await client.get(Q + '/', params={'tab': 'inbox'})).json()['items']
    assert first['request_id'] in [r['id'] for r in inbox]
    assert first['request_id'] in [
        r['id']
        for r in (await client.get(Q + '/', params={'tab': 'mine'})).json()['items']
    ]
    detail = (await client.get(f'{Q}/{first["request_id"]}')).json()
    assert detail['can_triage'] and [a['label'] for a in detail['answers']][:2] == [
        'What do you need?',
        'Request type',
    ]
    assert (
        detail['routing_trace'][0]['matched']
        and detail['routing_trace'][0]['actions'][0]['status'] == 'applied'
    )

    asked = await client.post(
        f'{Q}/{first["request_id"]}/request-info', json={'question': 'Which model?'}
    )
    assert asked.status_code == 200 and asked.json()['status'] == 'needs_info'
    noted = await client.post(
        f'{Q}/{first["request_id"]}/replies',
        json={'text': 'checking stock', 'visibility': 'internal'},
    )
    assert [m['visibility'] for m in noted.json()['conversation']] == [
        'requester',
        'internal',
    ]

    target = await _project(client, 'IT work')
    accepted = await client.post(
        f'{Q}/{first["request_id"]}/accept',
        json={'mode': 'item', 'project_id': target['id']},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert (
        body['status'] == 'accepted'
        and body['decision'] == 'accepted_item'
        and body['result_task_id']
    )
    again = await client.post(
        f'{Q}/{first["request_id"]}/accept', json={'mode': 'in_place'}
    )
    assert (
        again.status_code == 409 and again.json()['extra']['code'] == 'already_decided'
    )

    done = await client.post(f'{T}/{body["result_task_id"]}/complete')
    assert done.status_code in (200, 204), done.text
    assert (await client.get(f'{Q}/{first["request_id"]}')).json()['status'] == 'done'

    csv = await client.get(
        f'{F}/{form["id"]}/responses/export', params={'format': 'csv'}
    )
    assert (
        csv.status_code == 200
        and 'New laptop' in csv.text
        and 'What do you need?' in csv.text
    )


async def test_public_form_tracking_reply_withdraw_and_close(client: httpx.AsyncClient):
    queue = await _project(client)
    form = await _publish(
        client, (await _form(client, queue['id'], audience='public'))['id']
    )
    public_id = form['public_id']
    assert public_id and len(public_id) >= 22
    async with _public(client) as anon:
        page = (await anon.get(f'/api/v1/ppm/public-forms/{public_id}')).json()
        assert (
            page['status'] == 'published'
            and page['version'] == 1
            and 'routing' not in page['definition']
        )
        trap = await anon.post(
            f'/api/v1/ppm/public-forms/{public_id}/submissions',
            json={'answers': ANSWERS, 'website': 'x'},
        )
        assert trap.status_code == 201 and trap.json()['request_id'] == ''
        missing = await anon.post(
            f'/api/v1/ppm/public-forms/{public_id}/submissions',
            json={'answers': ANSWERS},
        )
        assert (
            missing.status_code == 400
            and missing.json()['extra']['code'] == 'invalid_answers'
        )
        sent = await anon.post(
            f'/api/v1/ppm/public-forms/{public_id}/submissions',
            json={
                'answers': ANSWERS,
                'requester_name': 'Jane Doe',
                'requester_email': 'Jane@Client.io',
            },
        )
        assert sent.status_code == 201, sent.text
        tracking = sent.json()['tracking_url']
        token = tracking.rsplit('/', 1)[1]
        view = (await anon.get(f'/api/v1/ppm/public-requests/{token}')).json()
        assert (
            view['status'] == 'submitted'
            and 'queue_project_id' not in view
            and view['can_withdraw']
        )

        request_id = sent.json()['request_id']
        detail = (await client.get(f'{Q}/{request_id}')).json()
        assert {k: v for k, v in detail['requester'].items() if v is not None} == {
            'is_member': False,
            'name': 'Jane Doe',
            'email': 'jane@client.io',
        }
        await client.post(
            f'{Q}/{request_id}/request-info', json={'question': 'Which office?'}
        )
        await client.post(
            f'{Q}/{request_id}/replies',
            json={'text': 'internal only', 'visibility': 'internal'},
        )
        view = (await anon.get(f'/api/v1/ppm/public-requests/{token}')).json()
        assert view['status'] == 'needs_info'
        assert [m['text'] for m in view['conversation']] == ['Which office?'] and view[
            'conversation'
        ][0].get('author') is None

        replied = await anon.post(
            f'/api/v1/ppm/public-requests/{token}/replies', json={'text': 'Paris'}
        )
        assert replied.status_code == 200 and replied.json()['status'] == 'in_review'
        assert replied.json()['conversation'][-1]['from_requester']
        withdrawn = await anon.post(f'/api/v1/ppm/public-requests/{token}/withdraw')
        assert withdrawn.json()['status'] == 'withdrawn'
        twice = await anon.post(f'/api/v1/ppm/public-requests/{token}/withdraw')
        assert twice.status_code == 409
        assert (
            await anon.get('/api/v1/ppm/public-requests/not-a-token')
        ).status_code == 404

        rotated = (await client.post(f'{F}/{form["id"]}/rotate-link')).json()
        assert rotated['public_id'] != public_id
        assert (
            await anon.get(f'/api/v1/ppm/public-forms/{public_id}')
        ).status_code == 404
        await client.post(f'{F}/{form["id"]}/close')
        closed = (
            await anon.get(f'/api/v1/ppm/public-forms/{rotated["public_id"]}')
        ).json()
        assert closed['status'] == 'closed' and closed.get('definition') is None
        refused = await anon.post(
            f'/api/v1/ppm/public-forms/{rotated["public_id"]}/submissions',
            json={
                'answers': ANSWERS,
                'requester_name': 'J',
                'requester_email': 'j@client.io',
            },
        )
        assert (
            refused.status_code == 409
            and refused.json()['extra']['code'] == 'form_closed'
        )


async def test_round_robin_reject_merge_in_place_and_project(client: httpx.AsyncClient):
    queue = await _project(client)
    form = await _form(client, queue['id'])
    form = await _patch(
        client,
        form,
        draft=form['draft']
        | {
            'routing': [
                {
                    'name': 'Everyone',
                    'conditions': [],
                    'actions': [
                        {'type': 'assign_round_robin', 'users': ['a@x.io', 'b@x.io']}
                    ],
                }
            ]
        },
    )
    await _publish(client, form['id'])
    ids = [
        (await _submit(client, form['id'], ANSWERS | {'summary': f'Ask {i}'}))[
            'request_id'
        ]
        for i in range(4)
    ]
    owners = [(await client.get(f'{T}/{i}')).json().get('user_id') for i in ids]
    assert owners == ['a@x.io', 'b@x.io', 'a@x.io', 'b@x.io']

    no_reason = await client.post(f'{Q}/{ids[0]}/reject', json={'reason': ' '})
    assert no_reason.status_code == 400
    rejected = (
        await client.post(f'{Q}/{ids[0]}/reject', json={'reason': 'Out of scope'})
    ).json()
    assert (
        rejected['status'] == 'rejected'
        and rejected['decision_reason'] == 'Out of scope'
    )

    merged = (
        await client.post(f'{Q}/{ids[2]}/merge', json={'original_id': ids[1]})
    ).json()
    assert merged['status'] == 'duplicate' and merged['duplicate_of'] == ids[1]
    original = (await client.get(f'{Q}/{ids[1]}')).json()
    assert any(
        m['visibility'] == 'internal' and 'Merged' in m['text']
        for m in original['conversation']
    )

    in_place = (
        await client.post(f'{Q}/{ids[1]}/accept', json={'mode': 'in_place'})
    ).json()
    assert (
        in_place['decision'] == 'accepted_in_place'
        and in_place['result_task_id'] == ids[1]
    )
    assert in_place['status'] in ('accepted', 'in_progress')

    as_project = await client.post(
        f'{Q}/{ids[3]}/accept', json={'mode': 'project', 'name': 'Laptop rollout'}
    )
    assert as_project.status_code == 200, as_project.text
    project_id = as_project.json()['result_project_id']
    assert as_project.json()['status'] == 'accepted'
    assert (await client.get(f'{P}/{project_id}')).json()['name'] == 'Laptop rollout'

    closed = (
        await client.get(
            Q + '/', params={'tab': 'all', 'form_id': form['id'], 'status': 'closed'}
        )
    ).json()
    assert {r['id'] for r in closed['items']} == {ids[0], ids[2]}
    statuses = (await client.get(f'{Q}/statuses')).json()
    assert [s['key'] for s in statuses if s['open']] == [
        'submitted',
        'in_review',
        'needs_info',
    ]
