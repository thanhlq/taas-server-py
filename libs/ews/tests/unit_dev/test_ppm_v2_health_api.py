"""PPM V2 project health on the local database (taas-specs/ppm/health/project-health-spec.md): today's health from the
rules (Ppm-1601…1607), the "why?" evidence (Ppm-1611), stale snapshots recomputed on read and by the job
(Ppm-1612), history (Ppm-1613), ``ppm.project.health_changed`` (Ppm-1614), the list badge (Ppm-1615), the manual
override (Ppm-1610) and the policy with its project exception (Ppm-1609). Development sign-in (all permissions)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from foundation.db.advanced_db_manager import db_context_session

P = '/api/v1/projects'
T = '/api/v1/tasks'


def _iso(day: date) -> str:
    return f'{day.isoformat()}T00:00:00'


async def _project(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        f'{P}/', json={'name': f'Health {uuid.uuid4().hex[:6]}', 'code': 'HE', **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _task(client: httpx.AsyncClient, project_id: str, name: str, **extra) -> dict:
    res = await client.post(
        f'{T}/', json={'project_id': project_id, 'name': name, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _dim(health: dict, key: str) -> dict:
    return next(d for d in health['dimensions'] if d['key'] == key)


async def _audit(project_id: str) -> list[str]:
    rows: list[str] = []
    from foundation.db.advanced_db_manager import MainDatabase
    from sqlalchemy import text

    async with MainDatabase.get_instance().get_engine().begin() as conn:
        result = await conn.execute(
            text(
                "select event from taas_ppm_audit_events where project_id = :p and event like 'ppm.project.health%'"
            ),
            {'p': project_id},
        )
        rows = [r[0] for r in result.all()]
    return rows


@db_context_session(auto_commit=True)
async def _refresh(organization_id, *, session=None) -> int:
    from ews.ppm import _health

    return await _health.refresh(session, organization_id=organization_id)


async def test_health_from_rules_with_evidence_and_list_badge(
    client: httpx.AsyncClient, test_org
):
    day = datetime.now(UTC).date()
    project = await _project(
        client,
        start_date=_iso(day - timedelta(days=20)),
        due_date=_iso(day + timedelta(days=10)),
    )
    pid = project['id']
    late = [
        await _task(client, pid, f'Late {i}', due_date=_iso(day - timedelta(days=2)))
        for i in range(3)
    ]
    for i in range(2):
        await _task(
            client,
            pid,
            f'Open {i}',
            due_date=_iso(day + timedelta(days=30)),
            user_id=test_org.email,
        )
    await _task(client, pid, 'Unowned soon', due_date=_iso(day + timedelta(days=3)))

    res = await client.get(f'{P}/{pid}/health')
    assert res.status_code == 200, res.text
    h = res.json()
    schedule = _dim(h, 'schedule')
    # 0 % done after 67 % of the time → slip 67 > 30 → 🔴; 3 of 6 open items overdue (50 %) → 🔴
    assert schedule['rating'] == 'red'
    s7 = next(r for r in schedule['reasons'] if r['rule'] == 'S7')
    assert s7['params']['n'] == 3 and {e['id'] for e in s7['evidence']} == {
        t['id'] for t in late
    }
    resources = _dim(h, 'resources')
    # every open item without an owner due within 14 days (3 late + 1 soon)
    assert (
        resources['rating'] == 'amber' and resources['reasons'][0]['params']['n'] == 4
    )
    assert (
        _dim(h, 'budget')['rating'] == 'none'
    )  # budgets: ⭐⭐⭐ capability, not tracked at ⭐⭐
    assert h['overall'] == 'red' and h['overall_effective'] == 'red'
    assert h['status_suggestion'] == 'At Risk' and h['can_override'] is True

    # the list carries the latest effective rating
    page = (await client.get(f'{P}/', params={'q': project['name']})).json()
    assert page['items'][0]['health'] == 'red'

    # a change makes today's snapshot stale: the next read recomputes (no more overdue items → S7 green)
    for t in late:
        assert (
            await client.patch(
                f'{T}/{t["id"]}', json={'due_date': _iso(day + timedelta(days=5))}
            )
        ).status_code == 200
    again = (await client.get(f'{P}/{pid}/health')).json()
    assert (
        next(r for r in _dim(again, 'schedule')['reasons'] if r['rule'] == 'S7')[
            'rating'
        ]
        == 'green'
    )
    assert again['computed_at'] > h['computed_at']

    history = (await client.get(f'{P}/{pid}/health/history')).json()['items']
    assert [d['snapshot_date'] for d in history] == [day.isoformat()]


async def test_override_lifecycle_and_events(client: httpx.AsyncClient, sql, test_org):
    day = datetime.now(UTC).date()
    project = await _project(
        client,
        start_date=_iso(day - timedelta(days=30)),
        due_date=_iso(day - timedelta(days=1)),
    )
    pid = project['id']
    h = (await client.get(f'{P}/{pid}/health')).json()
    assert h['overall'] == 'red'  # past the due date (S3)

    bad = await client.put(
        f'{P}/{pid}/health/override', json={'rating': 'amber', 'reason': 'short'}
    )
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'reason_required'
    far = await client.put(
        f'{P}/{pid}/health/override',
        json={
            'rating': 'amber',
            'reason': 'Change request signed',
            'expires_on': (day + timedelta(days=200)).isoformat(),
        },
    )
    assert far.status_code == 400 and far.json()['extra']['code'] == 'invalid_expiry'
    none = await client.put(
        f'{P}/{pid}/health/override',
        json={'rating': 'none', 'reason': 'Change request signed'},
    )
    assert none.status_code == 400 and none.json()['extra']['code'] == 'invalid_rating'

    res = await client.put(
        f'{P}/{pid}/health/override',
        json={'rating': 'amber', 'reason': 'CR-12 signed, +15 % budget approved'},
    )
    assert res.status_code == 200, res.text
    o = res.json()
    assert (o['overall'], o['overall_effective']) == ('red', 'amber')
    assert o['override']['expires_on'] == (day + timedelta(days=14)).isoformat()

    # expired yesterday → the job expires it and the effective rating is the computed one again
    await sql(
        "update taas_ppm_health_overrides set expires_on = :d where project_id = :p and status = 'active'",
        {'d': day - timedelta(days=1), 'p': pid},
    )
    await sql(
        "update taas_ppm_health_snapshots set computed_at = computed_at - interval '1 day' where project_id = :p",
        {'p': pid},
    )
    await _refresh(test_org.organization_id)
    after = (await client.get(f'{P}/{pid}/health')).json()
    assert after['overall_effective'] == 'red' and 'override' not in after

    res = await client.put(
        f'{P}/{pid}/health/override',
        json={'rating': 'green', 'reason': 'Client accepted the new date'},
    )
    assert res.json()['overall_effective'] == 'green'
    cleared = (await client.delete(f'{P}/{pid}/health/override')).json()
    assert cleared['overall_effective'] == 'red'

    topics = await _audit(pid)
    assert 'ppm.project.health_override_set' in topics
    assert 'ppm.project.health_override_expired' in topics
    assert 'ppm.project.health_override_cleared' in topics
    assert 'ppm.project.health_changed' in topics


async def test_policy_organization_and_project_exception(
    client: httpx.AsyncClient, test_org
):
    day = datetime.now(UTC).date()
    project = await _project(
        client,
        start_date=_iso(day - timedelta(days=10)),
        due_date=_iso(day + timedelta(days=10)),
    )
    pid = project['id']
    await _task(
        client,
        pid,
        'Half way',
        due_date=_iso(day + timedelta(days=5)),
        user_id=test_org.email,
    )
    h = (await client.get(f'{P}/{pid}/health')).json()
    s5 = next(r for r in _dim(h, 'schedule')['reasons'] if r['rule'] == 'S5')
    assert (s5['params']['slip'], s5['rating']) == (50, 'red')

    org = (await client.get('/api/v1/ppm/health-policy')).json()
    assert (
        org.get('source', 'default') in ('default', 'organization')
        and org['thresholds']['schedule']['slip_red'] == 30
    )
    stale = await client.patch(
        '/api/v1/ppm/health-policy',
        json={'version': org.get('version', 0) + 5, 'thresholds': {}},
    )
    assert stale.status_code == 409 and stale.json()['extra']['code'] == 'stale_policy'
    bad = await client.patch(
        '/api/v1/ppm/health-policy',
        json={
            'version': org.get('version', 0),
            'thresholds': {'schedule': {'slip_amber': 90}},
        },
    )
    assert bad.status_code == 400 and bad.json()['extra']['code'] == 'invalid_policy'

    # project exception: schedule not tracked → overall from the other dimensions
    own = (await client.get(f'{P}/{pid}/health-policy')).json()
    res = await client.patch(
        f'{P}/{pid}/health-policy',
        json={
            'version': own.get('version', 0),
            'dimensions': ['resources', 'scope', 'quality', 'risk'],
        },
    )
    assert res.status_code == 200, res.text
    assert (
        res.json()['source'] == 'project' and 'schedule' not in res.json()['dimensions']
    )
    h = (await client.get(f'{P}/{pid}/health')).json()
    assert (
        _dim(h, 'schedule')['reasons'][0]['code'] == 'not_tracked'
        and h['overall'] != 'red'
    )
    assert h.get('policy_version', 0) >= 1

    # organization thresholds: slip ≤ 60 is fine → 🟢 once the exception is dropped
    res = await client.patch(
        '/api/v1/ppm/health-policy',
        json={
            'version': org.get('version', 0),
            'thresholds': {'schedule': {'slip_amber': 55, 'slip_red': 60}},
        },
    )
    assert res.status_code == 200, res.text
    assert (await client.delete(f'{P}/{pid}/health-policy')).json()[
        'source'
    ] == 'organization'
    h = (await client.get(f'{P}/{pid}/health')).json()
    assert (
        next(r for r in _dim(h, 'schedule')['reasons'] if r['rule'] == 'S5')['rating']
        == 'green'
    )
    reset = (await client.get('/api/v1/ppm/health-policy')).json()
    await client.patch(
        '/api/v1/ppm/health-policy',
        json={
            'version': reset.get('version', 0),
            'thresholds': {'schedule': {'slip_amber': None, 'slip_red': None}},
        },
    )
