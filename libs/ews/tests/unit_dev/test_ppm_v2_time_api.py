"""PPM V2 time tracking on the local database (taas-specs/ppm/time-expense/time-tracking-spec.md): effort of items
(Ppm-1202 … 1205), entries and their rules (Ppm-1213, 1214), the timer (Ppm-1211), the weekly timesheet with cells,
submit, approval per project section, locks, corrections and reopen (Ppm-1230 … 1243), project time + CSV (Ppm-1250).
Development sign-in; a second person (a real user account) approves."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest

P = '/api/v1/projects'
T = '/api/v1/tasks'
TIME = '/api/v1/ppm'
H = 60


def dev_cookie(email: str) -> str:
    raw = json.dumps({'email': email, 'name': 'Lead'}).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


async def _project(client: httpx.AsyncClient) -> str:
    res = await client.post(
        f'{P}/', json={'name': f'Time {uuid.uuid4().hex[:6]}', 'code': 'TM'}
    )
    assert res.status_code == 201, res.text
    return res.json()['id']


async def _task(client: httpx.AsyncClient, pid: str, name: str, **extra) -> dict:
    res = await client.post(f'{T}/', json={'project_id': pid, 'name': name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
async def approver(app, test_org, sql) -> AsyncIterator[httpx.AsyncClient]:
    """A second person of the organization (project admin of the projects it is added to)."""
    user_id = uuid.uuid4()
    email = f'lead-{user_id.hex[:8]}@example.test'
    await sql(
        'insert into taas_user_account (id, email, username, email_verified, joined_at, login_count, '
        'is_root_account, failed_reset_attempts, mfa_enabled, created_at, updated_at, tenant_id, directory_id) '
        'values (:id, :email, :email, true, current_date, 0, false, 0, false, now(), now(), :t, :sub)',
        {
            'id': user_id,
            'email': email,
            't': test_org.tenant_id,
            'sub': f'sub-{user_id.hex[:10]}',
        },
    )
    await sql(
        'insert into taas_organization_members (id, user_id, organization_id, role, is_owner, created_at, '
        "updated_at, tenant_id, joined_via) values (:id, :u, :o, 'org_member', false, now(), now(), :t, 'join_link')",
        {
            'id': uuid.uuid7(),
            'u': user_id,
            'o': test_org.organization_id,
            't': test_org.tenant_id,
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://testserver',
        cookies={'taas_dev_session': dev_cookie(email)},
        headers={
            'X-Tenant-ID': str(test_org.tenant_id),
            'X-Organization-Id': str(test_org.organization_id),
            'Origin': 'http://testserver',
        },
    ) as c:
        c.user_id = str(user_id)  # type: ignore[attr-defined]
        c.email = email  # type: ignore[attr-defined]
        yield c
    await sql('delete from taas_casbin_rule where v0 = :u', {'u': str(user_id)})
    await sql(
        'delete from taas_organization_members where user_id = :id', {'id': user_id}
    )
    await sql('delete from taas_user_account where id = :id', {'id': user_id})


async def test_effort_remaining_variance_and_rollup(client: httpx.AsyncClient):
    pid = await _project(client)
    parent = await _task(client, pid, 'Payments')
    item = await _task(
        client, pid, 'Payment API', parent_id=parent['id'], estimated_minutes=16 * H
    )
    res = await client.post(
        f'{T}/{item["id"]}/timelogs', json={'entry_date': _today(), 'minutes': 21 * H}
    )
    assert res.status_code == 201, res.text
    assert res.json().get('status', 'draft') == 'draft' and res.json().get(
        'editable', True
    )

    effort = (await client.get(f'{T}/{item["id"]}/effort')).json()
    assert (effort['actual_minutes'], effort.get('remaining_minutes', 0)) == (21 * H, 0)
    assert effort['variance_pct'] == 31 and effort['variance_alert_level'] == 'warning'
    # Ppm-1203: typed remaining → manual; forecast 25h, +56% → critical
    got = (
        await client.patch(f'{T}/{item["id"]}', json={'remaining_minutes': 4 * H})
    ).json()
    assert got['remaining_manual'] is True and got['forecast_minutes'] == 25 * H
    assert got['variance_pct'] == 56 and got['variance_alert_level'] == 'critical'
    # roll-up on the parent (§5.2)
    p = (await client.get(f'{T}/{parent["id"]}')).json()
    assert (
        p['rollup_estimated_minutes'] == 16 * H
        and p['rollup_forecast_minutes'] == 25 * H
    )
    # back to auto
    auto = (
        await client.patch(f'{T}/{item["id"]}', json={'clear': ['remaining_minutes']})
    ).json()
    assert (
        auto.get('remaining_manual', False) is False
        and auto['forecast_minutes'] == 21 * H
    )


async def test_entry_rules_and_timer(client: httpx.AsyncClient):
    pid = await _project(client)
    item = await _task(client, pid, 'Webhooks')
    # the day after today in the earliest time zone (UTC+14) is the first refused day
    tomorrow = ((datetime.now(UTC) + timedelta(hours=14)).date() + timedelta(days=1)).isoformat()
    for body, code in (
        ({'task_id': item['id'], 'minutes': 0}, 'invalid_minutes'),
        ({'task_id': item['id'], 'minutes': 30, 'entry_date': tomorrow}, 'future_date'),
        ({'task_id': item['id'], 'minutes': 1441}, 'daily_max'),
        ({'category': 'training', 'minutes': 30, 'is_billable': True}, 'not_billable'),
        ({'category': 'project', 'minutes': 30}, 'invalid_category'),
    ):
        res = await client.post(f'{TIME}/time-entries', json=body)
        assert res.status_code == 400 and res.json()['extra']['code'] == code, (
            body,
            res.text,
        )
    internal = await client.post(
        f'{TIME}/time-entries', json={'category': 'training', 'minutes': 30}
    )
    assert internal.status_code == 201 and internal.json()['category'] == 'training'
    assert internal.json().get('project_id') is None

    started = await client.post(f'{TIME}/timers/start', json={'task_id': item['id']})
    assert started.status_code == 201 and started.json()['is_recording'] is True
    second = await client.post(f'{TIME}/timers/start', json={'category': 'internal'})
    current = (await client.get(f'{TIME}/timers/current')).json()
    assert [c['id'] for c in current] == [second.json()['id']]
    first = next(
        e
        for e in (await client.get(f'{TIME}/time-entries')).json()
        if e['id'] == started.json()['id']
    )
    assert first.get('is_recording', False) is False and first['minutes'] >= 1
    stopped = (await client.post(f'{TIME}/timers/stop')).json()
    assert (
        stopped[0]['minutes'] >= 1
        and (await client.get(f'{TIME}/timers/current')).json() == []
    )

    # editable entries: update, soft delete
    entry = internal.json()['id']
    assert (
        await client.patch(f'{TIME}/time-entries/{entry}', json={'minutes': 45})
    ).json()['minutes'] == 45
    assert (await client.delete(f'{TIME}/time-entries/{entry}')).status_code == 204


async def test_timesheet_cells_submit_approve_lock_correct_reopen(
    client: httpx.AsyncClient, approver: httpx.AsyncClient
):
    pid = await _project(client)
    member = await client.put(
        f'{P}/{pid}/members',
        json={'user_id': approver.user_id, 'role': 'project_admin'},  # type: ignore[attr-defined]
    )
    assert member.status_code in (200, 201), member.text
    item = await _task(client, pid, 'Data migration')
    # a week of its own (two weeks ago): other tests log time this week
    week = (datetime.now(UTC).date() - timedelta(days=14)).isoformat()
    sheet = (await client.get(f'{TIME}/timesheets/', params={'week': week})).json()
    assert sheet['status'] == 'open' and sheet['period_start'] <= week
    monday = sheet['days'][0]
    res = await client.put(
        f'{TIME}/timesheets/{sheet["id"]}/cells',
        json={'cells': [{'task_id': item['id'], 'entry_date': monday, 'minutes': 120}]},
    )
    assert res.status_code == 200, res.text
    row = res.json()['rows'][0]
    assert row['task_code'] == item['code'] and row['cells'][monday]['minutes'] == 120
    res = await client.put(
        f'{TIME}/timesheets/{sheet["id"]}/cells',
        json={'cells': [{'task_id': item['id'], 'entry_date': monday, 'minutes': 90}]},
    )
    assert res.json()['total_minutes'] == 90

    submitted = await client.post(f'{TIME}/timesheets/{sheet["id"]}/submit')
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()['status'] == 'submitted'
    assert [s['status'] for s in submitted.json()['sections']] == ['pending']
    blocked = await client.put(
        f'{TIME}/timesheets/{sheet["id"]}/cells',
        json={'cells': [{'task_id': item['id'], 'entry_date': monday, 'minutes': 60}]},
    )
    assert blocked.status_code == 409 and blocked.json()['extra']['code'] == 'locked'

    queue = (await approver.get(f'{TIME}/timesheets/approvals')).json()
    assert [q['id'] for q in queue] == [sheet['id']]
    seen = (await approver.get(f'{TIME}/timesheets/{sheet["id"]}')).json()
    assert seen['user_id'] == sheet['user_id']
    no_note = await approver.post(f'{TIME}/timesheets/{sheet["id"]}/reject', json={})
    assert (
        no_note.status_code == 400
        and no_note.json()['extra']['code'] == 'comment_required'
    )
    approved = await approver.post(f'{TIME}/timesheets/{sheet["id"]}/approve', json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()['status'] == 'approved'

    entries = (
        await client.get(f'{TIME}/time-entries', params={'task_id': item['id']})
    ).json()
    assert entries[0]['status'] == 'approved' and entries[0]['locked'] is True
    locked = await client.patch(
        f'{TIME}/time-entries/{entries[0]["id"]}', json={'minutes': 30}
    )
    assert locked.status_code == 409 and locked.json()['extra']['code'] == 'locked'

    # Ppm-1243: a correction = reversal + corrected entry in the current week
    short = await client.post(
        f'{TIME}/time-entries/{entries[0]["id"]}/correct',
        json={'minutes': 60, 'reason': 'x'},
    )
    assert (
        short.status_code == 400 and short.json()['extra']['code'] == 'reason_required'
    )
    fixed = await client.post(
        f'{TIME}/time-entries/{entries[0]["id"]}/correct',
        json={'minutes': 60, 'reason': 'Billed the wrong hours'},
    )
    assert fixed.status_code == 201, fixed.text
    assert [e['minutes'] for e in fixed.json()] == [-90, 60]
    assert fixed.json()[0]['kind'] == 'adjustment'
    assert fixed.json()[0]['entry_date'] == _today()

    # an approver reopens the approved week; its entries become editable again
    reopened = await approver.post(
        f'{TIME}/timesheets/{sheet["id"]}/reopen',
        json={'reason': 'Correction requested'},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()['status'] == 'reopened'
    again = (
        await client.get(
            f'{TIME}/time-entries',
            params={'task_id': item['id'], 'date_to': sheet['period_end']},
        )
    ).json()
    assert again and all(
        e.get('status', 'draft') == 'draft' and e.get('editable', True) for e in again
    )

    project_time = (await client.get(f'{P}/{pid}/time-entries')).json()
    assert (
        project_time['minutes'] >= 60
        and project_time['by_item'][0]['key'] == item['code']
    )
    csv = await client.get(f'{P}/{pid}/time-entries.csv')
    assert csv.status_code == 200 and csv.text.startswith('date,person,item')


async def test_auto_approval_mode(client: httpx.AsyncClient):
    settings = (await client.get('/api/v1/ppm/settings')).json()
    res = await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': settings['version'],
            'settings': {'time': {'approval_mode': 'auto'}},
        },
    )
    assert res.status_code == 200, res.text
    pid = await _project(client)
    item = await _task(client, pid, 'Docs')
    next_week = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    sheet = (await client.get(f'{TIME}/timesheets/', params={'week': next_week})).json()
    await client.post(
        f'{T}/{item["id"]}/timelogs',
        json={'entry_date': sheet['days'][0], 'minutes': 60},
    )
    done = (await client.post(f'{TIME}/timesheets/{sheet["id"]}/submit')).json()
    assert done['status'] == 'approved'
    bad = await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': res.json()['version'],
            'settings': {'time': {'rounding': 'up:7'}},
        },
    )
    assert bad.status_code == 400
    await client.patch(
        '/api/v1/ppm/settings',
        json={
            'version': res.json()['version'],
            'settings': {'time': {'approval_mode': None}},
        },
    )
