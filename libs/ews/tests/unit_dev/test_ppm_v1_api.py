"""PPM V1 on the local database (taas-specs/ppm/roadmap.md): capability levels (Ppm-0009), events + audit / Activity
(Ppm-0008, Ppm-0011, Ppm-0520), subtasks + roll-ups (Ppm-0815…0818), complete / reopen (Ppm-0807), owner +
collaborators (Ppm-0825…0827), comments with rich text and mentions (Ppm-0501…0512), clearing project dates.
Development sign-in (all permissions) unless stated."""

from __future__ import annotations

import uuid

import httpx

P = '/api/v1/projects'
T = '/api/v1/tasks'


async def _project(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        f'{P}/', json={'name': f'V1 {uuid.uuid4().hex[:6]}', 'code': 'VO', **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _task(client: httpx.AsyncClient, project_id: str, name: str, **extra) -> dict:
    res = await client.post(
        f'{T}/', json={'project_id': project_id, 'name': name, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _get(client: httpx.AsyncClient, task_id: str) -> dict:
    res = await client.get(f'{T}/{task_id}')
    assert res.status_code == 200, res.text
    return res.json()


async def test_ppm0009_capability_levels_and_settings(client: httpx.AsyncClient):
    res = await client.get('/api/v1/ppm/settings')
    assert res.status_code == 200, res.text
    body = res.json()
    caps = {c['key']: c for c in body['capabilities']}
    assert (
        body['level'] == 2
        and caps['gantt']['enabled']
        and not caps['resources']['enabled']
    )
    assert (
        caps['projects']['core'] and body['settings']['editors']['default'] == 'visual'
    )
    version = body.get('version', 0)

    res = await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': version,
            'level': 1,
            'capabilities': {'calendar': False, 'gantt': True, 'projects': False},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    caps = {c['key']: c['enabled'] for c in body['capabilities']}
    assert (
        body['level'] == 1
        and caps['gantt']
        and not caps['calendar']
        and not caps['time_tracking']
    )
    assert caps['projects'], 'core capabilities stay on'
    assert body['overrides'] == {'calendar': False, 'gantt': True}

    stale = await client.patch(
        '/api/v1/ppm/settings', json={'version': version, 'level': 3}
    )
    assert (
        stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_settings'
    )
    bad = await client.patch(
        '/api/v1/ppm/settings',
        json={'version': body['version'], 'settings': {'editors': {'enabled': []}}},
    )
    assert bad.status_code == 400

    res = await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': body['version'],
            'level': 2,
            'capabilities': {'calendar': None, 'gantt': None},
            'settings': {
                'editors': {'default': 'markdown', 'enabled': ['markdown', 'visual']}
            },
        },
    )
    assert res.status_code == 200, res.text
    assert (
        res.json().get('overrides', {}) == {}
        and res.json()['settings']['editors']['default'] == 'markdown'
    )
    await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': res.json()['version'],
            'settings': {
                'editors': {'default': 'visual', 'enabled': ['visual', 'markdown']}
            },
        },
    )


async def test_ppm0815_subtasks_hierarchy_rollups_and_delete(client: httpx.AsyncClient):
    project = await _project(client)
    pid = project['id']
    root = await _task(client, pid, 'Root')
    a = await _task(client, pid, 'A', parent_id=root['id'], estimated_minutes=60)
    b = await _task(client, pid, 'B', parent_id=root['id'], estimated_minutes=180)
    aa = await _task(client, pid, 'AA', parent_id=a['id'])

    parent = await _get(client, root['id'])
    assert (
        parent.get('child_count', 0) == 2
        and parent.get('done_child_count', 0) == 0
        and parent.get('progress', 0) == 0
    )

    deep = await client.post(
        f'{T}/', json={'project_id': pid, 'name': 'too deep', 'parent_id': aa['id']}
    )
    assert deep.status_code == 400 and deep.json()['extra']['code'] == 'hierarchy_depth'
    cycle = await client.patch(f'{T}/{root["id"]}', json={'parent_id': aa['id']})
    assert (
        cycle.status_code == 400 and cycle.json()['extra']['code'] == 'hierarchy_cycle'
    )
    other = await _project(client)
    foreign = await client.post(
        f'{T}/', json={'project_id': other['id'], 'name': 'x', 'parent_id': root['id']}
    )
    assert foreign.status_code == 400

    # Weighted by estimates (all counted children have one): B done = 180 / 240 → 75 %.
    res = await client.post(f'{T}/{b["id"]}/complete')
    assert res.status_code == 200, res.text
    assert res.json()['completed_at'] and res.json()['completed_by']
    parent = await _get(client, root['id'])
    assert parent.get('done_child_count', 0) == 1 and parent.get('progress', 0) == 75

    # Completing a parent with open subtasks asks first (Ppm-0818), cascade completes them.
    ask = await client.post(f'{T}/{a["id"]}/complete')
    assert ask.status_code == 409 and ask.json()['extra'] == {
        'code': 'open_subtasks',
        'count': 1,
    }
    res = await client.post(f'{T}/{a["id"]}/complete', params={'cascade': 'true'})
    assert res.status_code == 200 and (await _get(client, aa['id']))['completed_at']
    assert (await _get(client, root['id'])).get('progress', 0) == 100

    reopened = await client.post(f'{T}/{b["id"]}/reopen')
    assert reopened.status_code == 200 and reopened.json().get('completed_at') is None
    assert reopened.json()['stage_id'] == b['stage_id'], (
        'back to the stage it was completed from'
    )

    # Re-parent to top level with clear; both chains recalculate.
    res = await client.patch(f'{T}/{b["id"]}', json={'clear': ['parent_id']})
    assert res.status_code == 200 and res.json().get('parent_id') is None
    assert (await _get(client, root['id'])).get('child_count', 0) == 1

    listing = await client.get(
        f'{T}/', params={'project_id': pid, 'parent_id': root['id']}
    )
    assert [t['name'] for t in listing.json()['items']] == ['A']

    assert (await client.delete(f'{T}/{a["id"]}')).status_code == 204
    assert (await client.get(f'{T}/{aa["id"]}')).status_code == 404, (
        'the subtree goes with its parent'
    )
    assert (await _get(client, root['id'])).get('child_count', 0) == 0


async def test_ppm0825_owner_collaborators_and_events(
    client: httpx.AsyncClient, test_org
):
    project = await _project(client)
    task = await _task(
        client,
        project['id'],
        'Shared',
        user_id='ann@example.test',
        collaborator_ids=['bob@example.test'],
    )
    assert task['user_id'] == 'ann@example.test' and task['collaborators'] == [
        'bob@example.test'
    ]
    assert set(task['watchers']) >= {'ann@example.test', 'bob@example.test'}

    # Making a collaborator owner turns the previous owner into a collaborator (Ppm-0827).
    res = await client.patch(f'{T}/{task["id"]}', json={'user_id': 'bob@example.test'})
    assert res.json()['user_id'] == 'bob@example.test' and res.json()[
        'collaborators'
    ] == ['ann@example.test']
    res = await client.put(
        f'{T}/{task["id"]}/assignees',
        json={'owner_id': None, 'collaborator_ids': ['cy@example.test']},
    )
    assert res.json().get('user_id') is None and res.json()['collaborators'] == [
        'cy@example.test'
    ]

    activity = (await client.get(f'{T}/{task["id"]}/activity')).json()
    events = [a['event'] for a in activity]
    assert (
        'ppm.task.created' in events
        and 'ppm.task.assigned' in events
        and 'ppm.task.unassigned' in events
    )
    assert all(a['actor']['ref'] == test_org.email for a in activity)
    people = (
        await client.get(f'{T}/{task["id"]}/activity', params={'type': 'people'})
    ).json()
    assert people and all(
        a['event'].startswith('ppm.task.') and 'assign' in a['event'] for a in people
    )
    project_activity = (await client.get(f'{P}/{project["id"]}/activity')).json()
    assert any(a['event'] == 'ppm.project.created' for a in project_activity)


async def test_ppm0501_comments_rich_text_mentions_edit_delete(
    client: httpx.AsyncClient, test_org
):
    project = await _project(client)
    task = await _task(client, project['id'], 'Discuss')
    html = (
        '<p>Hi <span data-type="mention" data-id="ann@example.test" data-label="Ann">@Ann</span>'
        '<script>alert(1)</script></p>'
    )
    res = await client.post(
        f'{T}/{task["id"]}/comments',
        json={'html': html, 'user_id': 'spoof@example.test'},
    )
    assert res.status_code == 201, res.text
    comment = res.json()
    assert comment['user_id'] == test_org.email, 'author from the session (Ppm-0502)'
    assert '<script>' not in comment['html'] and comment['text'] == 'Hi @Ann'
    assert (
        comment['mentions'] == ['ann@example.test']
        and comment['can_edit']
        and comment['can_delete']
    )

    res = await client.patch(
        f'{T}/{task["id"]}/comments/{comment["id"]}', json={'text': 'Edited'}
    )
    assert (
        res.status_code == 200
        and res.json()['text'] == 'Edited'
        and res.json()['edited_at']
    )

    assert (
        await client.delete(f'{T}/{task["id"]}/comments/{comment["id"]}')
    ).status_code == 204
    listed = (await client.get(f'{T}/{task["id"]}/comments')).json()
    assert listed[0]['deleted'] and listed[0].get('text') is None, (
        'placeholder of a deleted comment (Ppm-0504)'
    )

    events = [
        a['event'] for a in (await client.get(f'{T}/{task["id"]}/activity')).json()
    ]
    for topic in (
        'ppm.comment.created',
        'ppm.task.mentioned',
        'ppm.comment.updated',
        'ppm.comment.deleted',
    ):
        assert topic in events, topic

    res = await client.post(
        f'{P}/{project["id"]}/comments', json={'text': 'Kick-off on Monday'}
    )
    assert res.status_code == 201 and res.json()['subject_type'] == 'project'
    assert [
        c['text'] for c in (await client.get(f'{P}/{project["id"]}/comments')).json()
    ] == ['Kick-off on Monday']


async def test_project_dates_clear_kind_and_description_sanitized(
    client: httpx.AsyncClient,
):
    project = await _project(
        client, start_date='2026-10-01T00:00:00Z', due_date='2026-12-01T00:00:00Z'
    )
    res = await client.patch(
        f'{P}/{project["id"]}', json={'clear': ['start_date', 'due_date']}
    )
    assert res.status_code == 200, res.text
    assert res.json().get('start_date') is None and res.json().get('due_date') is None
    assert (
        res.json()['kind'] == 'project'
        and 'ppm.task:update' in res.json()['permissions']
    )
    assert (
        await client.patch(f'{P}/{project["id"]}', json={'clear': ['name']})
    ).status_code == 400

    res = await client.patch(
        f'{P}/{project["id"]}',
        json={
            'settings': {'editors': {'default': 'markdown', 'enabled': ['markdown']}}
        },
    )
    assert res.json()['editors'] == {'default': 'markdown', 'enabled': ['markdown']}
    res = await client.patch(
        f'{P}/{project["id"]}', json={'settings': {'editors': None}}
    )
    assert res.json()['editors']['enabled'] == ['visual', 'markdown'], (
        'back to the organization default'
    )
    res = await client.patch(
        f'{P}/{project["id"]}',
        json={'settings': {'notifications': {'off': ['ppm:task_commented']}}},
    )
    assert res.json()['settings']['notifications'] == {'off': ['ppm:task_commented']}
    bad = {'settings': {'notifications': {'off': ['ppm:task_mentioned']}}}
    assert (await client.patch(f'{P}/{project["id"]}', json=bad)).status_code == 400, (
        'mandatory kind'
    )

    task = await _task(
        client,
        project['id'],
        'Doc',
        description_html='<p>Safe<img src=x onerror=alert(1)></p>',
    )
    assert task['description_html'] == '<p>Safe</p>' and task['description'] == 'Safe'


async def test_ppm0830_checklist_counts_mandatory_reorder_convert(
    client: httpx.AsyncClient,
):
    project = await _project(client)
    task = await _task(client, project['id'], 'Release', progress_mode='checklist')
    base = f'{T}/{task["id"]}/checklist-items'
    a = (await client.post(base, json={'name': 'Changelog'})).json()
    b = (
        await client.post(
            base,
            json={
                'name': 'Sign-off',
                'is_mandatory': True,
                'assignee_user_id': 'ann@example.test',
            },
        )
    ).json()
    c = (
        await client.post(
            base, json={'name': 'Announce', 'due_date': '2026-11-02T00:00:00Z'}
        )
    ).json()
    assert [i['name'] for i in (await client.get(base)).json()] == [
        'Changelog',
        'Sign-off',
        'Announce',
    ]

    res = await client.patch(f'{base}/{a["id"]}', json={'is_completed': True})
    assert res.json()['is_completed'] and res.json()['completed_by']
    current = await _get(client, task['id'])
    assert (
        current['checklist_total'] == 3
        and current['checklist_done'] == 1
        and current['progress'] == 33
    )

    blocked = await client.post(f'{T}/{task["id"]}/complete')
    assert (
        blocked.status_code == 409
        and blocked.json()['extra']['code'] == 'checklist_incomplete'
    )
    assert blocked.json()['extra']['items'] == ['Sign-off']

    order = await client.put(f'{base}/order', json={'ids': [c['id'], a['id']]})
    assert [i['name'] for i in order.json()] == ['Announce', 'Changelog', 'Sign-off']

    sub = await client.post(f'{base}/{b["id"]}/convert')
    assert sub.status_code == 201, sub.text
    assert (
        sub.json()['parent_id'] == task['id']
        and sub.json()['user_id'] == 'ann@example.test'
    )
    current = await _get(client, task['id'])
    assert current['checklist_total'] == 2 and current['child_count'] == 1
    assert (
        await client.post(f'{T}/{task["id"]}/complete', params={'cascade': 'true'})
    ).status_code == 200

    assert (await client.delete(f'{base}/{c["id"]}')).status_code == 204
    events = [
        a['event']
        for a in (
            await client.get(f'{T}/{task["id"]}/activity', params={'type': 'checklist'})
        ).json()
    ]
    assert {
        'ppm.checklist_item.created',
        'ppm.checklist_item.completed',
        'ppm.checklist_item.deleted',
    } <= set(events)


def _as(app, test_org, email: str) -> httpx.AsyncClient:
    import base64
    import json

    cookie = (
        base64.urlsafe_b64encode(json.dumps({'email': email, 'name': email}).encode())
        .rstrip(b'=')
        .decode()
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://testserver',
        cookies={'taas_dev_session': cookie},
        headers={
            'X-Organization-Id': str(test_org.organization_id),
            'Origin': 'http://testserver',
        },
    )


async def test_ppm1700_notifications_assign_mention_comment_and_reminders(
    client: httpx.AsyncClient, app, test_org, sql
):
    from datetime import UTC, datetime, timedelta

    bob_email = f'bob-{uuid.uuid4().hex[:6]}@example.test'
    project = await _project(client)
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime('%Y-%m-%dT00:00:00Z')
    task = await _task(
        client, project['id'], 'Fix login', user_id=bob_email, due_date=tomorrow
    )

    async with _as(app, test_org, bob_email) as bob:
        inbox = (await bob.get('/api/v1/notifications/')).json()
        assigned = [n for n in inbox if n['kind'] == 'ppm:task_assigned']
        assert len(assigned) == 1 and assigned[0]['link'].endswith(
            f'/ppm/projects/{project["id"]}?task={task["id"]}'
        )
        assert (
            assigned[0]['actor_ref'] == test_org.email
            and 'Fix login' in assigned[0]['title']
        )

        html = f'<p>Please check <span data-type="mention" data-id="{bob_email}">@bob</span></p>'
        await client.post(f'{T}/{task["id"]}/comments', json={'html': html})
        kinds = [n['kind'] for n in (await bob.get('/api/v1/notifications/')).json()]
        assert 'ppm:task_mentioned' in kinds and 'ppm:task_commented' not in kinds, (
            'a mention replaces the comment'
        )
        await client.post(f'{T}/{task["id"]}/comments', json={'text': 'Deployed'})
        kinds = [n['kind'] for n in (await bob.get('/api/v1/notifications/')).json()]
        assert 'ppm:task_commented' in kinds

        count = (await bob.get('/api/v1/notifications/unread-count')).json()['unread']
        assert count == 3
        first = (
            await bob.get('/api/v1/notifications/', params={'unread': 'true'})
        ).json()[0]
        assert (await bob.post(f'/api/v1/notifications/{first["id"]}/read')).json()[
            'read_at'
        ]
        assert (await bob.get('/api/v1/notifications/unread-count')).json()[
            'unread'
        ] == 2
        await bob.post('/api/v1/notifications/read-all')
        assert (await bob.get('/api/v1/notifications/unread-count')).json().get(
            'unread', 0
        ) == 0

        # The actor is never notified (Ppm-1702); other users cannot read Bob's rows.
        mine = [n['kind'] for n in (await client.get('/api/v1/notifications/')).json()]
        assert 'ppm:task_assigned' not in mine
        assert (
            await client.post(f'/api/v1/notifications/{first["id"]}/read')
        ).status_code == 404

        # Due tomorrow → the hourly reminder job, once per day (dedup).
        from ews.notifications._delivery import _JOBS, _run_job

        await _run_job(_JOBS['ppm.due_reminders'])
        await _run_job(_JOBS['ppm.due_reminders'])
        soon = [
            n
            for n in (await bob.get('/api/v1/notifications/')).json()
            if n['kind'] == 'ppm:task_due_soon'
        ]
        assert len(soon) == 1

        prefs = (await bob.get('/api/v1/notifications/preferences')).json()
        assert {'ppm:task_assigned', 'ppm:task_mentioned'} <= {
            k['key'] for k in prefs['kinds']
        }
        bad = await bob.put(
            '/api/v1/notifications/preferences',
            json={
                'preferences': [
                    {
                        'app': 'ppm',
                        'kind': 'ppm:task_mentioned',
                        'channel': 'in_app',
                        'mode': 'off',
                    }
                ]
            },
        )
        assert bad.status_code == 400, 'mentions cannot be switched off in the app'
        res = await bob.put(
            '/api/v1/notifications/preferences',
            json={
                'preferences': [
                    {
                        'app': 'ppm',
                        'kind': 'ppm:task_assigned',
                        'channel': 'email',
                        'mode': 'off',
                    }
                ],
                'settings': {
                    'time_zone': 'Europe/Paris',
                    'digest': 'weekly',
                    'digest_hour': 9,
                },
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()['settings']['time_zone'] == 'Europe/Paris'


async def test_ppm0840_project_drive_task_folder_upload_and_links(
    client: httpx.AsyncClient,
):
    project = await _project(client)
    task = await _task(client, project['id'], 'Spec')
    files = (await client.get(f'{T}/{task["id"]}/files')).json()
    assert files['drive_id'] and files['folder_id']
    again = (await client.get(f'{T}/{task["id"]}/files')).json()
    assert again == files, 'one drive per project, one folder per item'
    assert (await client.get(f'{P}/{project["id"]}/files')).json()['drive_id'] == files[
        'drive_id'
    ]

    drive = (await client.get(f'/api/v1/files/drives/{files["drive_id"]}')).json()
    assert drive['kind'] == 'project' and drive['source_id'] == project['id']
    up = await client.post(
        f'/api/v1/files/drives/{files["drive_id"]}/files',
        files={'file': ('spec.txt', b'hello spec', 'text/plain')},
        data={'parent_id': files['folder_id']},
    )
    assert up.status_code == 201, up.text
    listed = await client.get(
        f'/api/v1/files/drives/{files["drive_id"]}/nodes',
        params={'parent_id': files['folder_id']},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    names = [n['name'] for n in (body['items'] if isinstance(body, dict) else body)]
    assert names == ['spec.txt']

    drives = (await client.get('/api/v1/files/drives/')).json()
    assert all(d['kind'] != 'project' for d in drives), (
        'project drives are sources, not drives'
    )
    members = await client.put(
        f'/api/v1/files/drives/{files["drive_id"]}/members',
        json={'user_id': str(uuid.uuid4()), 'role': 'drive_viewer'},
    )
    assert members.status_code == 400

    link = await client.post(
        f'{T}/{task["id"]}/links',
        json={'url': 'https://figma.com/file/abc', 'title': 'Figma'},
    )
    assert link.status_code == 201 and link.json()['title'] == 'Figma'
    assert (
        await client.post(
            f'{T}/{task["id"]}/links', json={'url': 'javascript:alert(1)'}
        )
    ).status_code == 400
    assert [x['url'] for x in (await client.get(f'{T}/{task["id"]}/links')).json()] == [
        'https://figma.com/file/abc'
    ]
    assert (
        await client.delete(f'{T}/{task["id"]}/links/{link.json()["id"]}')
    ).status_code == 204
    plink = await client.post(
        f'{P}/{project["id"]}/links', json={'url': 'https://wiki.example/x'}
    )
    assert plink.json()['title'] == 'wiki.example'
    assert [
        x['id'] for x in (await client.get(f'{P}/{project["id"]}/links')).json()
    ] == [plink.json()['id']]


async def test_ppm0901_my_work_buckets_plans_snooze_quick_add_inbox(
    client: httpx.AsyncClient, test_org
):
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    day = lambda n: (today + timedelta(days=n)).isoformat() + 'T00:00:00Z'  # noqa: E731
    project = await _project(client)
    pid = project['id']
    overdue = await _task(
        client,
        pid,
        'Fix payment API',
        user_id=test_org.email,
        due_date=day(-2),
        priority=4,
    )
    due_today = await _task(
        client, pid, 'Review proposal', user_id=test_org.email, due_date=day(0)
    )
    collab = await _task(
        client,
        pid,
        'Pair review',
        user_id='lan@example.test',
        collaborator_ids=[test_org.email],
    )
    other = await _task(
        client, pid, 'Not mine', user_id='lan@example.test', due_date=day(0)
    )
    holder = await _task(client, pid, 'Launch', user_id='lan@example.test')
    step = (
        await client.post(
            f'{T}/{holder["id"]}/checklist-items',
            json={
                'name': 'Sign the PR',
                'assignee_user_id': test_org.email,
                'due_date': day(1),
            },
        )
    ).json()

    res = await client.get(
        '/api/v1/ppm/my-work/', params={'tz': 'UTC', 'project_id': pid}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    by = {e['source_id']: e for e in body['entries']}
    assert other['id'] not in by
    assert (
        by[overdue['id']]['bucket'] == 'overdue'
        and by[overdue['id']]['overdue_reason'] == 'due'
    )
    assert by[due_today['id']]['bucket'] == 'today'
    assert (
        by[collab['id']]['bucket'] == 'no_date'
        and by[collab['id']]['role'] == 'collaborator'
    )
    assert (
        by[step['id']]['source_type'] == 'checklist_item'
        and by[step['id']]['bucket'] == 'tomorrow'
    )
    assert body['counts']['overdue'] == 1 and body['counts']['today'] == 1

    # Planning moves the entry, never the due date (ADR-18).
    plan = await client.put(
        f'/api/v1/ppm/my-work/plans/task/{collab["id"]}',
        json={'planned_date': today.isoformat()},
    )
    assert plan.status_code == 200, plan.text
    body = (
        await client.get(
            '/api/v1/ppm/my-work/', params={'tz': 'UTC', 'project_id': pid}
        )
    ).json()
    assert {e['source_id']: e for e in body['entries']}[collab['id']][
        'bucket'
    ] == 'today'
    assert (await _get(client, collab['id'])).get('due_date') is None

    # Snooze hides until then; the snoozed filter lists it.
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    await client.put(
        f'/api/v1/ppm/my-work/plans/task/{due_today["id"]}',
        json={'snoozed_until': later},
    )
    ids = [
        e['source_id']
        for e in (
            await client.get('/api/v1/ppm/my-work/', params={'project_id': pid})
        ).json()['entries']
    ]
    assert due_today['id'] not in ids
    snoozed = (
        await client.get(
            '/api/v1/ppm/my-work/', params={'project_id': pid, 'snoozed': 'true'}
        )
    ).json()['entries']
    assert [e['source_id'] for e in snoozed] == [due_today['id']]

    # Reschedule overdue → today (planned dates only).
    res = await client.post(
        '/api/v1/ppm/my-work/reschedule',
        params={'tz': 'UTC'},
        json={'planned_date': today.isoformat()},
    )
    assert res.status_code == 200 and res.json()['badge'] >= 1
    body = (await client.get('/api/v1/ppm/my-work/', params={'project_id': pid})).json()
    assert {e['source_id']: e for e in body['entries']}[overdue['id']][
        'bucket'
    ] == 'today'

    # Completing closes the entry and drops the plan; it shows in "Done today".
    await client.post(f'{T}/{overdue["id"]}/complete')
    body = (await client.get('/api/v1/ppm/my-work/', params={'project_id': pid})).json()
    assert overdue['id'] not in [e['source_id'] for e in body['entries']]
    assert overdue['id'] in [d['task_id'] for d in body['done_today']]

    # Quick add without a project → my Inbox (created once), priority token.
    res = await client.post(
        '/api/v1/ppm/my-work/tasks',
        json={'name': 'Call the bank !4', 'planned_date': today.isoformat()},
    )
    assert res.status_code == 201, res.text
    task = res.json()
    assert (
        task['name'] == 'Call the bank'
        and task['priority'] == 4
        and task['user_id'] == test_org.email
    )
    body = (await client.get('/api/v1/ppm/my-work/', params={'inbox': 'true'})).json()
    assert body['inbox_project_id'] == task['project_id']
    assert [e['source_id'] for e in body['entries']] == [task['id']]
    assert body['entries'][0]['project']['kind'] == 'personal'
    again = (
        await client.post('/api/v1/ppm/my-work/tasks', json={'name': 'Second'})
    ).json()
    assert again['project_id'] == task['project_id']
    listed = (await client.get(f'{P}/', params={'limit': 200})).json()['items']
    assert task['project_id'] not in [p['id'] for p in listed], (
        'the Inbox is never a listed project'
    )
    members = await client.put(
        f'{P}/{task["project_id"]}/members',
        json={'user_id': str(uuid.uuid4()), 'role': 'project_member'},
    )
    assert (
        members.status_code == 409
        and members.json()['extra']['code'] == 'personal_project'
    )

    counts = (
        await client.get('/api/v1/ppm/my-work/counts', params={'tz': 'UTC'})
    ).json()
    assert counts['badge'] >= 2


async def test_overview_metrics_bulk_and_exports(client: httpx.AsyncClient, test_org):
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    project = await _project(
        client,
        start_date=(today - timedelta(days=10)).isoformat() + 'T00:00:00Z',
        due_date=(today + timedelta(days=10)).isoformat() + 'T00:00:00Z',
    )
    pid = project['id']
    late = await _task(
        client,
        pid,
        '=HYPERLINK("x")',
        user_id='ann@example.test',
        due_date=(today - timedelta(days=1)).isoformat() + 'T00:00:00Z',
    )
    soon = await _task(
        client,
        pid,
        'Soon',
        due_date=(today + timedelta(days=3)).isoformat() + 'T00:00:00Z',
    )
    await _task(client, pid, 'Done one')
    done = (await client.get(f'{T}/', params={'project_id': pid})).json()['items'][-1]
    await client.post(f'{T}/{done["id"]}/complete')

    m = (await client.get(f'{P}/{pid}/metrics')).json()
    assert (
        m['total'] == 3 and m['done'] == 1 and m['overdue'] == 1 and m['due_soon'] == 1
    )
    assert [t['id'] for t in m['overdue_tasks']] == [late['id']] and soon['id'] in [
        t['id'] for t in m['upcoming_tasks']
    ]
    assert m['schedule']['health'] == 'atRisk' and m['schedule']['elapsed'] == 50, (
        '50 % elapsed, 33 % done' and m['progress'] == 33
    )
    assert m['people'][0]['user'] == 'ann@example.test'

    o = (await client.get('/api/v1/ppm/overview', params={'recent': 50})).json()
    assert o['total'] >= 1 and pid in [p['id'] for p in o['recent']]
    assert sum(s['count'] for s in o['statuses']) == o['total'] and all(
        s['color'] for s in o['statuses']
    )

    other = await _project(client)
    res = await client.post(
        f'{P}/bulk',
        json={
            'ids': [pid, other['id'], str(uuid.uuid4())],
            'action': 'update',
            'status': 'On Hold',
            'add_labels': ['q4'],
        },
    )
    assert res.status_code == 200, res.text
    assert (
        set(res.json()['done']) == {pid, other['id']}
        and res.json()['failed'][0]['status'] == 404
    )
    assert (await client.get(f'{P}/{pid}')).json()['status'] == 'On Hold'

    csv_res = await client.get(
        f'{P}/export.csv', params={'ids': f'{pid},{other["id"]}'}
    )
    assert csv_res.status_code == 200 and csv_res.headers['content-type'].startswith(
        'text/csv'
    )
    lines = csv_res.text.lstrip('﻿').splitlines()
    assert lines[0].startswith('Code,Name,Status') and len(lines) == 3
    tasks_csv = (await client.get(f'{T}/export.csv', params={'project_id': pid})).text
    assert "'=HYPERLINK" in tasks_csv, 'formula cells are neutralised'

    res = await client.post(
        f'{P}/bulk', json={'ids': [other['id']], 'action': 'delete'}
    )
    assert (
        res.json()['done'] == [other['id']]
        and (await client.get(f'{P}/{other["id"]}')).status_code == 404
    )


async def test_ppm0808_move_item_with_subtree(client: httpx.AsyncClient):
    a = await _project(client, code='AA')
    b = await _project(client, code='BB')
    parent = await _task(client, a['id'], 'Parent')
    child = await _task(client, a['id'], 'Child', parent_id=parent['id'])
    await client.post(f'{T}/{child["id"]}/comments', json={'text': 'keep me'})
    res = await client.post(f'{T}/{parent["id"]}/move', json={'project_id': b['id']})
    assert res.status_code == 200, res.text
    moved = res.json()
    assert moved['project_id'] == b['id'] and moved['code'].startswith('BB-')
    child_now = await _get(client, child['id'])
    assert child_now['project_id'] == b['id'] and child_now['parent_id'] == parent['id']
    assert [
        c['text'] for c in (await client.get(f'{T}/{child["id"]}/comments')).json()
    ] == ['keep me']
    assert (await client.get(f'{T}/', params={'project_id': a['id']})).json()[
        'items'
    ] == []
    same = await client.post(f'{T}/{parent["id"]}/move', json={'project_id': b['id']})
    assert same.status_code == 400


async def test_description_as_site_document(client: httpx.AsyncClient):
    project = await _project(client)
    doc = {
        'schemaVersion': 1,
        'sections': [
            {
                'id': 'body',
                'type': 'richText',
                'content': {
                    'type': 'doc',
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': 'Steps to reproduce'}],
                        }
                    ],
                },
            }
        ],
    }
    task = await _task(client, project['id'], 'Bug', description_doc=doc)
    assert (
        task['description_doc'] == doc and task['description'] == 'Steps to reproduce'
    )
    doc['sections'][0]['content']['content'][0]['content'][0]['text'] = 'Updated'
    res = await client.patch(
        f'{T}/{task["id"]}',
        json={'description_doc': doc, 'description_html': '<p>Updated</p>'},
    )
    assert (
        res.status_code == 200
        and res.json()['description'] == 'Updated'
        and res.json()['description_html'] == '<p>Updated</p>'
    )
    bad = await client.patch(
        f'{T}/{task["id"]}',
        json={
            'description_doc': {
                'schemaVersion': 1,
                'sections': [{'id': 'x', 'type': 'nope'}],
            }
        },
    )
    assert bad.status_code == 400 and bad.json()['extra']['issues']
    res = await client.patch(
        f'{T}/{task["id"]}',
        json={'clear': ['description_doc', 'description', 'description_html']},
    )
    assert (
        res.json().get('description_doc') is None
        and res.json().get('description') is None
    )
