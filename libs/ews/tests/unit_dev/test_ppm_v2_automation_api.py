"""PPM V2 automation on the local database (taas-specs/ppm/automation/automation-spec.md Part B): event rules run as
their owner (Ppm-1740…1747), skipped runs, run log, undo (Ppm-1750, 1751), loop guard, relative + scheduled rules
from the tick job (Ppm-1743, 1744), auto-pause after 3 failures (Ppm-1752), validation and dry-run (Ppm-1749).
Development sign-in (all permissions)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from foundation.db.advanced_db_manager import db_context_session

P = '/api/v1/projects'
T = '/api/v1/tasks'
R = '/api/v1/ppm/automation-rules'


def _iso(days: int) -> str:
    return f'{(datetime.now(UTC).date() + timedelta(days=days)).isoformat()}T00:00:00'


async def _project(client: httpx.AsyncClient) -> dict:
    res = await client.post(
        f'{P}/', json={'name': f'Auto {uuid.uuid4().hex[:6]}', 'code': 'AU'}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _task(client: httpx.AsyncClient, project_id: str, name: str, **extra) -> dict:
    res = await client.post(
        f'{T}/', json={'project_id': project_id, 'name': name, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _rule(client: httpx.AsyncClient, project_id: str, **rule) -> dict:
    res = await client.post(
        R, json={'project_id': project_id, 'name': 'Rule', 'status': 'active', **rule}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _tasks(client: httpx.AsyncClient, project_id: str) -> list[dict]:
    res = await client.get(f'{T}/', params={'project_id': project_id, 'limit': 100})
    body = res.json()
    return body['items'] if isinstance(body, dict) else body


@db_context_session(auto_commit=True)
async def _tick(organization_id, *, session=None) -> int:
    from ews.ppm import _automation

    return await _automation.tick(session, organization_id=organization_id)


async def test_event_rule_runs_as_owner_with_log_and_undo(client: httpx.AsyncClient):
    pid = (await _project(client))['id']
    rule = await _rule(
        client,
        pid,
        name='QA hand-off',
        trigger_type='event',
        trigger={'on': 'item_stage_changed', 'stage_type': 'done'},
        conditions=[{'field': 'item.priority', 'op': 'gte', 'value': 3}],
        actions=[
            {
                'type': 'create_item',
                'name': 'QA: {{item.name}}',
                'link': 'relates',
                'due_in_days': 2,
                'working_days': True,
            },
            {'type': 'set_field', 'field': 'labels_add', 'value': 'qa'},
            {
                'type': 'notify',
                'recipients': ['owner'],
                'message': '{{item.code}} done',
            },
        ],
    )
    high = await _task(client, pid, 'Payment API', priority=4)
    low = await _task(client, pid, 'Docs', priority=1)
    for t in (high, low):
        res = await client.patch(f'{T}/{t["id"]}', json={'stage_type': 'done'})
        assert res.status_code == 200, res.text

    names = {t['name'] for t in await _tasks(client, pid)}
    assert 'QA: Payment API' in names and 'QA: Docs' not in names
    labelled = (await client.get(f'{T}/{high["id"]}')).json()
    assert 'qa' in (labelled.get('labels') or [])

    runs = (await client.get(f'{R}/{rule["id"]}/runs')).json()
    by_status = {r['status'] for r in runs}
    assert by_status == {'succeeded', 'skipped'}
    done = next(r for r in runs if r['status'] == 'succeeded')
    assert [a['type'] for a in done['actions']] == [
        'create_item',
        'set_field',
        'notify',
    ]
    assert (
        await client.get(
            '/api/v1/ppm/automation-runs', params={'subject_id': high['id']}
        )
    ).json()[0]['id'] == done['id']

    # undo: the QA item is deleted and the label removed
    res = await client.post(f'/api/v1/ppm/automation-runs/{done["id"]}/undo')
    assert res.status_code == 200, res.text
    assert res.json()['status'] == 'undone'
    assert 'QA: Payment API' not in {t['name'] for t in await _tasks(client, pid)}
    assert 'qa' not in (
        (await client.get(f'{T}/{high["id"]}')).json().get('labels') or []
    )
    again = await client.post(f'/api/v1/ppm/automation-runs/{done["id"]}/undo')
    assert again.status_code == 409


async def test_loop_guard_validation_and_dry_run(client: httpx.AsyncClient):
    pid = (await _project(client))['id']
    bad = await client.post(
        R,
        json={
            'project_id': pid,
            'name': 'Bad',
            'trigger_type': 'event',
            'trigger': {'on': 'nope'},
            'actions': [],
        },
    )
    assert bad.status_code == 400
    assert {i['path'] for i in bad.json()['extra']['issues']} >= {
        'trigger.on',
        'actions',
    }

    # a rule that creates an item when an item is created never reacts to its own item
    await _rule(
        client,
        pid,
        trigger_type='event',
        trigger={'on': 'item_created'},
        actions=[{'type': 'create_item', 'name': 'Follow-up of {{item.name}}'}],
    )
    await _task(client, pid, 'Seed')
    names = sorted(t['name'] for t in await _tasks(client, pid))
    assert names == ['Follow-up of Seed', 'Seed']

    item = await _task(client, pid, 'Dry', priority=5)
    draft = {
        'trigger_type': 'event',
        'trigger': {'on': 'item_updated'},
        'conditions': [{'field': 'item.priority', 'op': 'eq', 'value': 5}],
        'actions': [{'type': 'set_field', 'field': 'priority', 'value': 1}],
    }
    res = await client.post(f'{R}/test', json={'item_id': item['id'], 'rule': draft})
    assert res.status_code == 200, res.text
    out = res.json()
    assert (
        out['matched']
        and out['actions'][0]['before'] == {'priority': 5}
        and out['actions'][0]['after'] == {'priority': 1}
    )
    assert (await client.get(f'{T}/{item["id"]}')).json()[
        'priority'
    ] == 5  # nothing saved


async def test_relative_schedule_and_auto_pause(
    client: httpx.AsyncClient, sql, test_org
):
    pid = (await _project(client))['id']
    late = await _task(client, pid, 'Late one', due_date=_iso(-3))
    await _task(client, pid, 'On time', due_date=_iso(5))
    relative = await _rule(
        client,
        pid,
        trigger_type='relative',
        trigger={'on': 'overdue_by', 'days': 1},
        actions=[{'type': 'add_comment', 'text': 'Overdue: {{item.code}}'}],
    )
    schedule = await _rule(
        client,
        pid,
        trigger_type='schedule',
        trigger={'every': 'daily', 'at': '08:00', 'for_each': 'project'},
        actions=[
            {
                'type': 'notify',
                'recipients': ['owner'],
                'message': 'Daily review of {{project.name}}',
            }
        ],
    )
    broken = await _rule(
        client,
        pid,
        trigger_type='event',
        trigger={'on': 'item_created'},
        actions=[{'type': 'add_checklist', 'template_id': str(uuid.uuid4())}],
    )
    for name in ('A', 'B', 'C'):
        await _task(client, pid, name)
    paused = (await client.get(f'{R}/{broken["id"]}')).json()
    assert paused['status'] == 'paused' and paused['failures'] == 3

    await sql(
        "update taas_ppm_automation_rules set next_run_at = now() - interval '1 minute' where id in (:a, :b)",
        {'a': relative['id'], 'b': schedule['id']},
    )
    assert await _tick(test_org.organization_id) >= 2
    runs = (await client.get(f'{R}/{relative["id"]}/runs')).json()
    assert [r['subject_id'] for r in runs if r['status'] == 'succeeded'] == [late['id']]
    assert (await client.get(f'{R}/{schedule["id"]}/runs')).json()[0][
        'status'
    ] == 'succeeded'
    # the same occurrence never runs twice
    await sql(
        "update taas_ppm_automation_rules set next_run_at = now() - interval '1 minute' where id = :a",
        {'a': relative['id']},
    )
    await _tick(test_org.organization_id)
    assert len((await client.get(f'{R}/{relative["id"]}/runs')).json()) == len(runs)

    # enable after a fix resets the failures; disable / delete
    res = await client.patch(
        f'{R}/{broken["id"]}',
        json={
            'version': paused.get('version', 1),
            'actions': [{'type': 'add_comment', 'text': 'ok'}],
        },
    )
    assert res.status_code == 200, res.text
    enabled = (await client.post(f'{R}/{broken["id"]}/enable')).json()
    assert enabled['status'] == 'active' and enabled.get('failures', 0) == 0
    assert (await client.delete(f'{R}/{broken["id"]}')).status_code == 204
    assert (await client.get(f'{R}/{broken["id"]}')).status_code == 404
