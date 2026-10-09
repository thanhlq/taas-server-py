"""PPM V2 schedule on the local database (taas-specs/ppm/schedule/schedule-spec.md): phases (Ppm-1001…1003), dependency
links + cycle check (Ppm-1020…1025), the Gantt payload with violations and "why this date" (Ppm-1024, 1063), auto
mode write-back, SNET on a new start, stale versions and batch changes (Ppm-1050, 1051, 1060, 1064). Development
sign-in (all permissions)."""

from __future__ import annotations

import uuid

import httpx

P = '/api/v1/projects'
T = '/api/v1/tasks'


async def _project(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        f'{P}/',
        json={
            'name': f'Sched {uuid.uuid4().hex[:6]}',
            'code': 'SC',
            'start_date': '2026-10-05T00:00:00',
            **extra,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _task(client: httpx.AsyncClient, project_id: str, name: str, **extra) -> dict:
    res = await client.post(
        f'{T}/', json={'project_id': project_id, 'name': name, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _link(
    client: httpx.AsyncClient, source: dict, target: dict, **extra
) -> httpx.Response:
    return await client.post(
        f'{T}/{target["id"]}/dependencies',
        json={'predecessor_id': source['id'], **extra},
    )


def _items(schedule: dict) -> dict[str, dict]:
    return {i['id']: i for i in schedule['items']}


async def test_phases_crud_order_and_items(client: httpx.AsyncClient):
    project = await _project(client)
    pid = project['id']
    design = (await client.post(f'{P}/{pid}/phases', json={'name': 'Design'})).json()
    build = (
        await client.post(
            f'{P}/{pid}/phases',
            json={'name': 'Build', 'color': '#22c55e', 'planned_start': '2026-10-12'},
        )
    ).json()
    assert [design['position'], build['position']] == [1, 2]
    bad = await client.patch(
        f'{P}/{pid}/phases/{build["id"]}', json={'planned_finish': '2026-10-01'}
    )
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'invalid_dates'

    parent = await _task(client, pid, 'Wireframes', phase_id=design['id'])
    assert parent['phase_id'] == design['id']
    child = await _task(client, pid, 'Home page', parent_id=parent['id'])
    res = await client.patch(f'{T}/{child["id"]}', json={'phase_id': build['id']})
    assert res.status_code == 400 and res.json()['extra']['code'] == 'phase_on_subtask'

    order = await client.put(
        f'{P}/{pid}/phases/order', json={'phase_ids': [build['id'], design['id']]}
    )
    assert [p['name'] for p in order.json()] == ['Build', 'Design']
    phases = (await client.get(f'{P}/{pid}/phases')).json()
    assert phases[1]['item_count'] == 1

    schedule = (await client.get(f'{P}/{pid}/schedule')).json()
    assert _items(schedule)[child['id']]['phase_id'] == design['id']  # inherited

    assert (await client.delete(f'{P}/{pid}/phases/{design["id"]}')).status_code == 204
    assert (await client.get(f'{T}/{parent["id"]}')).json().get('phase_id') is None


async def test_dependencies_cycle_and_relations(client: httpx.AsyncClient):
    project = await _project(client)
    pid = project['id']
    a, b, c = [await _task(client, pid, n) for n in ('A', 'B', 'C')]
    ab = await _link(client, a, b)
    assert ab.status_code == 201, ab.text
    assert ab.json()['type'] == 'fs' and ab.json()['direction'] == 'predecessor'
    assert (await _link(client, b, c, type='ss', lag_days=2)).status_code == 201

    cycle = await _link(client, c, a)
    assert cycle.status_code == 400
    assert cycle.json()['extra']['code'] == 'dependency_cycle'
    assert cycle.json()['extra']['path'] == [c['id'], a['id'], b['id'], c['id']]
    twice = await _link(client, b, a)
    assert twice.json()['extra']['code'] == 'invalid_link'
    self_link = await _link(client, a, a)
    assert self_link.json()['extra']['code'] == 'invalid_link'
    relates = await _link(client, a, c, type='relates')
    assert relates.status_code == 201
    no_lag = await _link(client, c, b, type='relates', lag_days=1)
    assert no_lag.json()['extra']['code'] == 'invalid_link'

    links = (await client.get(f'{T}/{b["id"]}/dependencies')).json()
    assert sorted(x['direction'] for x in links) == ['predecessor', 'successor']
    upd = await client.patch(
        f'{T}/{b["id"]}/dependencies/{ab.json()["id"]}', json={'lag_days': -1}
    )
    assert upd.json()['lag_days'] == -1

    # Ppm-1025: deleting an item deletes its links
    assert (await client.delete(f'{T}/{a["id"]}')).status_code == 204
    left = (await client.get(f'{T}/{b["id"]}/dependencies')).json()
    assert [x['source_task_id'] for x in left] == [b['id']]


async def test_manual_schedule_reports_violations(client: httpx.AsyncClient):
    project = await _project(client)
    pid = project['id']
    a = await _task(
        client,
        pid,
        'Spec',
        start_date='2026-10-05T00:00:00',
        due_date='2026-10-09T00:00:00',
    )
    b = await _task(
        client,
        pid,
        'Build',
        start_date='2026-10-07T00:00:00',
        due_date='2026-10-08T00:00:00',
    )
    m = await _task(client, pid, 'Launch', work_item_type='milestone')
    await _link(client, a, b)
    await _link(client, b, m)
    schedule = (await client.get(f'{P}/{pid}/schedule')).json()
    items = _items(schedule)
    assert schedule['settings']['mode'] == 'manual'
    assert items[b['id']]['why'] == 'manual'
    assert items[b['id']]['violations'][0]['days'] == 3
    assert items[m['id']]['milestone'] and items[m['id']]['due'] == '2026-10-08'
    assert (items[m['id']]['why'], items[m['id']]['driving_link_id']) == (
        'link',
        schedule['links'][1]['id'],
    )
    # manual mode writes nothing
    assert (await client.get(f'{T}/{m["id"]}')).json().get('due_date') is None
    bad = await client.patch(
        f'{T}/{a["id"]}', json={'start_date': '2026-10-20T00:00:00'}
    )
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'invalid_dates'


async def test_auto_mode_writes_back_and_follows_changes(client: httpx.AsyncClient):
    project = await _project(client)
    pid = project['id']
    a = await _task(client, pid, 'A', duration_days=3)
    b = await _task(client, pid, 'B', duration_days=2)
    await _link(client, a, b, lag_days=1)

    preview = (
        await client.post(f'{P}/{pid}/schedule/preview', json={'mode': 'auto'})
    ).json()
    assert {c['task_id'] for c in preview['changes']} == {a['id'], b['id']}
    stale = await client.patch(
        f'{P}/{pid}/schedule/settings', json={'mode': 'auto', 'base_version': 7}
    )
    assert (
        stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_schedule'
    )
    saved = await client.patch(
        f'{P}/{pid}/schedule/settings', json={'mode': 'auto', 'base_version': 0}
    )
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()['schedule_version'] == 1
        and saved.json()['settings']['mode'] == 'auto'
    )
    got_b = (await client.get(f'{T}/{b["id"]}')).json()
    assert (got_b['start_date'][:10], got_b['due_date'][:10]) == (
        '2026-10-09',
        '2026-10-12',
    )

    # a longer predecessor moves its successor in the same request (subscriber, Ppm-1060)
    await client.patch(f'{T}/{a["id"]}', json={'duration_days': 5})
    assert (await client.get(f'{T}/{b["id"]}')).json()['start_date'][
        :10
    ] == '2026-10-13'

    # a new start on an auto item becomes an SNET constraint (§7)
    res = await client.patch(
        f'{T}/{a["id"]}', json={'start_date': '2026-10-07T00:00:00'}
    )
    got_a = res.json()
    assert (
        got_a['constraint_type'] == 'snet'
        and got_a['constraint_date'][:10] == '2026-10-07'
    )
    schedule = (await client.get(f'{P}/{pid}/schedule')).json()
    assert _items(schedule)[a['id']]['why'] == 'constraint'
    assert _items(schedule)[b['id']]['start'] == '2026-10-15'

    # Gantt drop: several items at once on the current version
    version = schedule['schedule_version']
    drop = await client.post(
        f'{P}/{pid}/schedule/changes',
        json={
            'base_version': version,
            'changes': [
                {
                    'task_id': a['id'],
                    'clear': ['constraint_type', 'constraint_date'],
                    'progress': 40,
                }
            ],
        },
    )
    assert drop.status_code == 200, drop.text
    assert (
        drop.json()['updated'] == [a['id']]
        and drop.json()['schedule_version'] > version
    )
    assert (await client.get(f'{T}/{a["id"]}')).json()['start_date'][
        :10
    ] == '2026-10-05'
    again = await client.post(
        f'{P}/{pid}/schedule/changes', json={'base_version': version, 'changes': []}
    )
    assert again.status_code == 409


async def test_capability_switches_schedule_off(client: httpx.AsyncClient):
    project = await _project(client)
    settings = (await client.get('/api/v1/ppm/settings')).json()
    res = await client.patch(
        '/api/v1/ppm/settings',
        json={'version': settings['version'], 'capabilities': {'gantt': False}},
    )
    assert res.status_code == 200, res.text
    off = await client.get(f'{P}/{project["id"]}/schedule')
    assert (
        off.status_code == 403 and off.json()['extra']['code'] == 'capability_disabled'
    )
    await client.patch(
        '/api/v1/ppm/settings',
        json={'version': res.json()['version'], 'capabilities': {'gantt': None}},
    )


async def test_duplicate_keeps_phases_links_and_durations(client: httpx.AsyncClient):
    """Ppm-0884 with the schedule: phases (windows shifted), links (type, lag), item durations and modes."""
    project = await _project(client)
    pid = project['id']
    phase = (
        await client.post(
            f'{P}/{pid}/phases', json={'name': 'Build', 'planned_start': '2026-10-05'}
        )
    ).json()
    a = await _task(
        client,
        pid,
        'A',
        duration_days=2,
        phase_id=phase['id'],
        start_date='2026-10-05T00:00:00',
    )
    b = await _task(client, pid, 'B', duration_days=3, schedule_mode='auto')
    await _link(client, a, b, type='ss', lag_days=1)
    copy = await client.post(
        f'{P}/{pid}/duplicate', json={'name': 'Copy', 'start_date': '2026-10-12'}
    )
    assert copy.status_code in (200, 201), copy.text
    schedule = (await client.get(f'{P}/{copy.json()["id"]}/schedule')).json()
    assert [(p['name'], p['planned_start']) for p in schedule['phases']] == [
        ('Build', '2026-10-12')
    ]
    assert [(lk['type'], lk['lag_days']) for lk in schedule['links']] == [('ss', 1)]
    by_name = {i['name']: i for i in schedule['items']}
    assert (
        by_name['A']['phase_id'] == schedule['phases'][0]['id']
        and by_name['A']['duration'] == 2
    )
    # the auto item was written back after the copy: SS + 1 from A
    assert (by_name['B']['mode'], by_name['B']['start']) == ('auto', '2026-10-13')
