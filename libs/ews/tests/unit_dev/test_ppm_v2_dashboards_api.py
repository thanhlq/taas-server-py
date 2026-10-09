"""PPM V2 dashboards & reports on the local database (taas-specs/ppm/reporting/dashboards-reports-spec.md): the system
dashboards and their widgets (Ppm-1902, 1903, 1910), daily statistics + series (burnup), custom dashboards (create,
version, copy, shares, delete — Ppm-1930…1933), widget preview / export, the V2 reports (Ppm-1950) with CSV / XLSX
(Ppm-1970) and the PPM overview tiles (Ppm-1901). Development sign-in (all permissions)."""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
from foundation.db.advanced_db_manager import db_context_session

P = '/api/v1/projects'
T = '/api/v1/tasks'
D = '/api/v1/ppm/dashboards'


def _iso(days: int) -> str:
    return f'{(datetime.now(UTC).date() + timedelta(days=days)).isoformat()}T00:00:00'


async def _seed(client: httpx.AsyncClient, email: str) -> dict:
    project = (
        await client.post(
            f'{P}/',
            json={
                'name': f'Dash {uuid.uuid4().hex[:6]}',
                'code': 'DA',
                'start_date': _iso(-10),
                'due_date': _iso(20),
            },
        )
    ).json()
    pid = project['id']
    late = (
        await client.post(
            f'{T}/',
            json={
                'project_id': pid,
                'name': 'Late one',
                'due_date': _iso(-2),
                'user_id': email,
            },
        )
    ).json()
    await client.post(
        f'{T}/',
        json={
            'project_id': pid,
            'name': 'Soon one',
            'due_date': _iso(3),
            'user_id': email,
        },
    )
    await client.post(
        f'{T}/', json={'project_id': pid, 'name': 'Done one', 'stage_type': 'done'}
    )
    await client.post(
        f'{T}/',
        json={
            'project_id': pid,
            'name': 'Gate',
            'work_item_type': 'milestone',
            'due_date': _iso(5),
        },
    )
    res = await client.post(
        f'{T}/{late["id"]}/timelogs', json={'entry_date': _iso(-3)[:10], 'minutes': 90}
    )
    assert res.status_code in (200, 201), res.text
    return {'project': project, 'late': late}


def _rows(res: httpx.Response) -> list[list]:
    assert res.status_code == 200, res.text
    return res.json().get('rows', [])


@db_context_session(auto_commit=True)
async def _stats_job(organization_id, *, session=None) -> int:
    from ews.ppm import _stats

    return await _stats.refresh_job(session, organization_id=organization_id)


async def test_system_dashboards_series_and_overview(
    client: httpx.AsyncClient, test_org
):
    seed = await _seed(client, test_org.email)
    pid = seed['project']['id']
    assert await _stats_job(test_org.organization_id) >= 1

    board = (
        await client.get(f'{D}/system:project_overview', params={'project_id': pid})
    ).json()
    assert board['system_key'] == 'project_overview' and not board.get('can_edit')
    ids = {w['id'] for w in board['layout']['widgets']}
    assert {'health', 'open', 'burnup', 'milestones', 'workload', 'activity'} <= ids

    def data(wid: str):
        return client.get(
            f'{D}/system:project_overview/widgets/{wid}/data',
            params={'project_id': pid},
        )

    assert _rows(await data('open'))[-1][1] == 3  # late, soon, gate
    assert _rows(await data('overdue'))[-1][1] == 1
    burnup = _rows(await data('burnup'))
    assert burnup[-1][1:] == [4, 1]  # total, done
    assert [r[1] for r in _rows(await data('milestones'))] == ['Gate']
    workload = _rows(await data('workload'))
    assert [test_org.email.lower(), 2] in [[str(r[0]).lower(), r[1]] for r in workload]
    health = _rows(await data('health'))
    assert health[0][0] == 'overall' and len(health) == 7
    assert (
        await client.get(f'{D}/system:project_overview')
    ).status_code == 400  # project needed

    series = (
        await client.get(f'{P}/{pid}/metrics/series', params={'series': 'burndown'})
    ).json()
    assert series['columns'][1]['key'] == 'remaining' and series['rows']

    overview = (await client.get('/api/v1/ppm/overview')).json()
    assert (
        overview['my_overdue'] >= 1
        and overview['my_due_week'] >= 1
        and overview['open'] >= 1
    )

    mine = _rows(await client.get(f'{D}/system:my_dashboard/widgets/items/data'))
    assert {'Late one', 'Soon one'} <= {r[2] for r in mine}


async def test_custom_dashboard_lifecycle(client: httpx.AsyncClient, test_org):
    seed = await _seed(client, test_org.email)
    pid = seed['project']['id']
    layout = {
        'widgets': [
            {
                'id': 'bands',
                'type': 'bar',
                'x': 0,
                'y': 0,
                'w': 6,
                'h': 4,
                'query': {'source': 'items', 'group_by': 'band'},
            },
            {
                'id': 'note',
                'type': 'text',
                'x': 6,
                'y': 0,
                'w': 6,
                'h': 2,
                'text': 'Weekly review',
            },
        ]
    }
    res = await client.post(
        f'{D}/',
        json={'name': 'Mine', 'layout': layout, 'filters': {'project_ids': [pid]}},
    )
    assert res.status_code == 201, res.text
    board = res.json()
    assert board['can_edit'] and board['is_owner'] and board['version'] == 1
    bands = dict(_rows(await client.get(f'{D}/{board["id"]}/widgets/bands/data')))
    assert bands.get('done') == 1 and sum(bands.values()) == 4

    stale = await client.patch(f'{D}/{board["id"]}', json={'version': 9, 'name': 'X'})
    assert (
        stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_dashboard'
    )
    renamed = (
        await client.patch(f'{D}/{board["id"]}', json={'version': 1, 'name': 'Renamed'})
    ).json()
    assert renamed['name'] == 'Renamed' and renamed['version'] == 2
    bad = await client.patch(
        f'{D}/{board["id"]}',
        json={'version': 2, 'layout': {'widgets': [{'id': 'x', 'type': 'pie'}]}},
    )
    assert bad.status_code == 400

    shares = (
        await client.put(
            f'{D}/{board["id"]}/shares',
            json={'shares': [{'principal_id': 'Ann@Example.test', 'can_edit': True}]},
        )
    ).json()
    assert shares == [{'principal_id': 'ann@example.test', 'can_edit': True}]
    assert (await client.get(f'{D}/{board["id"]}')).json()['visibility'] == 'shared'

    copy = await client.post(
        f'{D}/system:ppm_overview/copy', json={'name': 'My overview'}
    )
    assert copy.status_code == 201, copy.text
    assert (
        copy.json()['scope_type'] == 'personal'
        and len(copy.json()['layout']['widgets']) == 4
    )
    listed = (await client.get(f'{D}/')).json()
    assert {'system:ppm_overview', board['id'], copy.json()['id']} <= {
        d['id'] for d in listed
    }

    preview = await client.post(
        '/api/v1/ppm/widget-data',
        json={'query': {'source': 'items', 'group_by': 'assignee'}, 'project_id': pid},
    )
    assert sum(r[1] for r in _rows(preview)) == 4
    xlsx = await client.post(
        f'{D}/{board["id"]}/widgets/bands/export',
        json={'format': 'xlsx', 'labels': {'band': 'Band'}},
    )
    assert xlsx.status_code == 200 and xlsx.headers['content-type'].startswith(
        'application/vnd.openxmlformats'
    )
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as z:
        assert 'Band' in z.read('xl/worksheets/sheet1.xml').decode()

    assert (await client.delete(f'{D}/{board["id"]}')).status_code == 204
    assert (await client.get(f'{D}/{board["id"]}')).status_code == 404
    assert (await client.delete(f'{D}/system:my_dashboard')).status_code == 403


async def test_reports_and_exports(client: httpx.AsyncClient, test_org):
    seed = await _seed(client, test_org.email)
    pid = seed['project']['id']
    catalog = (await client.get('/api/v1/ppm/reports/')).json()
    assert [r['key'] for r in catalog] == [
        'status',
        'overdue_items',
        'time_by_person',
        'time_by_project',
    ]

    status = (
        await client.post(
            '/api/v1/ppm/reports/status/run', json={'params': {'project_ids': [pid]}}
        )
    ).json()
    row = dict(
        zip([c['key'] for c in status['columns']], status['rows'][0], strict=True)
    )
    assert (row['open'], row['overdue'], row['progress'], row['next_milestone']) == (
        3,
        1,
        25,
        'Gate',
    )

    overdue = (
        await client.post(
            '/api/v1/ppm/reports/overdue_items/run',
            json={'params': {'project_ids': [pid]}},
        )
    ).json()
    assert [r[2] for r in overdue['rows']] == ['Late one'] and overdue['rows'][0][
        -1
    ] == 2

    period = {
        'project_ids': [pid],
        'date_from': _iso(-30)[:10],
        'date_to': _iso(0)[:10],
    }
    time = (
        await client.post(
            '/api/v1/ppm/reports/time_by_person/run', json={'params': period}
        )
    ).json()
    assert time['rows'][0][3] == 1.5  # 90 minutes = 1.5 h
    bad = await client.post(
        '/api/v1/ppm/reports/status/run', json={'params': {'date_from': '2026-01-01'}}
    )
    assert bad.status_code == 400

    csv = await client.post(
        '/api/v1/ppm/reports/time_by_project/export',
        json={'format': 'csv', 'params': period, 'labels': {'hours': 'Hours'}},
    )
    assert csv.status_code == 200 and 'attachment' in csv.headers['content-disposition']
    assert csv.content.decode('utf-8').startswith('﻿project_name,week,Hours')
