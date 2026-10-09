"""PPM V2 work model on the local database (taas-specs/ppm/work-model/work-model-spec.md): item type library +
behaviours (Ppm-0802…0806), custom fields (Ppm-0850…0857), checklist templates (Ppm-0833), approvals (Ppm-0865…0873),
project templates (Ppm-0880…0884) and recurring items (Ppm-0890). Development sign-in (all permissions)."""

from __future__ import annotations

import uuid

import httpx

P = '/api/v1/projects'
T = '/api/v1/tasks'
PPM = '/api/v1/ppm'


async def _project(client: httpx.AsyncClient, **extra) -> dict:
    res = await client.post(
        f'{P}/', json={'name': f'V2 {uuid.uuid4().hex[:6]}', 'code': 'VT', **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _task(client: httpx.AsyncClient, project_id: str, name: str, **extra) -> dict:
    res = await client.post(
        f'{T}/', json={'project_id': project_id, 'name': name, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_item_type_library_and_behaviours(client: httpx.AsyncClient):
    res = await client.get(f'{PPM}/item-behaviours')
    assert {b['key'] for b in res.json()} >= {'task', 'milestone', 'approval', 'risk'}
    types = (await client.get(f'{PPM}/item-types')).json()
    by_key = {t['key']: t for t in types}
    assert (
        by_key['milestone']['behaviour'] == 'milestone'
        and by_key['task']['origin'] == 'catalog'
    )
    assert by_key['risk']['behaviour'] == 'risk'

    custom = await client.post(
        f'{PPM}/item-types',
        json={'term': 'Contract review', 'behaviour': 'deliverable'},
    )
    assert custom.status_code == 201, custom.text
    assert (
        custom.json()['key'] == 'contract_review'
        and custom.json()['origin'] == 'custom'
    )

    project = await _project(client)
    milestone = await _task(
        client,
        project['id'],
        'Go-live',
        work_item_type='milestone',
        start_date='2026-10-01T00:00:00',
        due_date='2026-10-09T00:00:00',
        estimated_minutes=120,
    )
    assert milestone['behaviour'] == 'milestone'
    assert (
        milestone['start_date'] == milestone['due_date']
        and milestone.get('estimated_minutes') is None
    )

    # a used type cannot change its behaviour (409 in_use); archived types keep their items
    used = await _task(
        client, project['id'], 'Review MSA', work_item_type='contract_review'
    )
    assert used['behaviour'] == 'deliverable'
    res = await client.patch(
        f'{PPM}/item-types/{custom.json()["id"]}', json={'behaviour': 'task'}
    )
    assert res.status_code == 409 and res.json()['extra']['code'] == 'in_use'
    res = await client.post(f'{PPM}/item-types/{custom.json()["id"]}/archive')
    assert res.json()['archived'] is True

    # risks do not count in progress
    risk = await _task(client, project['id'], 'Vendor risk', work_item_type='risk')
    assert risk['behaviour'] == 'risk'
    detail = (await client.get(f'{P}/{project["id"]}')).json()
    assert detail.get('task_count', 0) == 2  # milestone + deliverable


async def test_custom_fields_bindings_values_filters(client: httpx.AsyncClient):
    project = await _project(client)
    severity = await client.post(
        f'{PPM}/custom-fields/',
        json={
            'label': 'Severity',
            'type': 'select',
            'config': {'options': [{'label': 'Low'}, {'label': 'High'}]},
        },
    )
    assert severity.status_code == 201, severity.text
    sev = severity.json()
    low, high = (o['id'] for o in sev['config']['options'])
    budget = (
        await client.post(
            f'{PPM}/custom-fields/',
            json={
                'label': 'Budget',
                'type': 'money',
                'project_id': project['id'],
                'config': {'decimals': 2, 'currency': 'EUR'},
            },
        )
    ).json()
    assert budget['project_id'] == project['id']

    # bind severity to bugs organization-wide (required before done), budget to every item of the project
    types = {t['key']: t for t in (await client.get(f'{PPM}/item-types')).json()}
    res = await client.put(
        f'{PPM}/item-types/{types["bug"]["id"]}/fields',
        json={
            'bindings': [
                {'field_id': sev['id'], 'required': 'before_done', 'on_card': True}
            ]
        },
    )
    assert res.status_code == 200, res.text
    res = await client.put(
        f'{P}/{project["id"]}/fields',
        json={
            'bindings': [{'field_id': budget['id'], 'default_value': {'amount': '100'}}]
        },
    )
    assert res.status_code == 200, res.text
    assert {b['field_id'] for b in res.json()['bindings']} >= {sev['id'], budget['id']}

    bug = await _task(
        client,
        project['id'],
        'Crash',
        work_item_type='bug',
        custom_fields={'severity': high},
    )
    assert bug['custom_fields'] == {
        'severity': high,
        'budget': {'amount': '100.00', 'currency': 'EUR'},
    }
    plain = await _task(client, project['id'], 'Plain task')
    assert plain['custom_fields'] == {'budget': {'amount': '100.00', 'currency': 'EUR'}}

    res = await client.post(
        f'{T}/',
        json={
            'project_id': project['id'],
            'name': 'x',
            'custom_fields': {'severity': 'nope'},
        },
    )
    assert (
        res.status_code == 400 and 'severity' in res.json()['extra']['issues']
    )  # not bound to tasks

    res = await client.patch(
        f'{T}/{plain["id"]}', json={'custom_fields': {'budget': {'amount': 'abc'}}}
    )
    assert res.status_code == 400 and res.json()['extra']['issues']['budget']

    res = await client.get(
        f'{T}/', params={'project_id': project['id'], 'cf_severity': high}
    )
    assert [t['id'] for t in res.json()['items']] == [bug['id']]
    res = await client.get(
        f'{T}/', params={'project_id': project['id'], 'cf_severity_empty': 'true'}
    )
    assert [t['id'] for t in res.json()['items']] == [plain['id']]
    res = await client.get(
        f'{T}/', params={'project_id': project['id'], 'cf_budget_gte': '50'}
    )
    assert len(res.json()['items']) == 2

    # required before done: clearing severity blocks completion
    res = await client.patch(
        f'{T}/{bug["id"]}', json={'custom_fields': {'severity': None}}
    )
    assert res.status_code == 200 and 'severity' not in res.json()['custom_fields']
    res = await client.post(f'{T}/{bug["id"]}/complete')
    assert res.status_code == 409 and res.json()['extra']['code'] == 'fields_required'
    await client.patch(f'{T}/{bug["id"]}', json={'custom_fields': {'severity': low}})
    assert (await client.post(f'{T}/{bug["id"]}/complete')).status_code == 200

    # the type never changes; activity carries cf_ changes
    res = await client.patch(f'{PPM}/custom-fields/{sev["id"]}', json={'type': 'text'})
    assert res.status_code == 409
    activity = (await client.get(f'{T}/{bug["id"]}/activity')).json()
    assert any('cf_severity' in (e.get('changes') or {}) for e in activity)


async def test_checklist_templates(client: httpx.AsyncClient):
    project = await _project(client)
    res = await client.post(
        f'{PPM}/checklist-templates/',
        json={
            'name': 'Release',
            'items': [{'name': 'Changelog', 'is_mandatory': True}, {'name': 'Tag'}],
        },
    )
    assert res.status_code == 201, res.text
    tpl = res.json()
    task = await _task(
        client, project['id'], 'Ship 1.0', checklist_template_id=tpl['id']
    )
    steps = (await client.get(f'{T}/{task["id"]}/checklist-items')).json()
    assert [s['name'] for s in steps] == ['Changelog', 'Tag'] and steps[0][
        'is_mandatory'
    ]

    other = await _task(client, project['id'], 'Ship 1.1')
    res = await client.post(
        f'{T}/{other["id"]}/checklist/apply-template',
        json={'checklist_template_id': tpl['id']},
    )
    assert res.json() == {'added': 2}
    res = await client.post(
        f'{T}/{task["id"]}/checklist/save-as-template',
        json={'name': 'Release copy', 'project_scope': True},
    )
    assert res.status_code == 201 and res.json()['project_id'] == project['id']
    listed = (
        await client.get(
            f'{PPM}/checklist-templates/', params={'project_id': project['id']}
        )
    ).json()
    assert {t['name'] for t in listed} >= {'Release', 'Release copy'}

    # an item type's default template applies to its new items
    types = {t['key']: t for t in (await client.get(f'{PPM}/item-types')).json()}
    await client.patch(
        f'{PPM}/item-types/{types["meeting"]["id"]}',
        json={'default_checklist_template_id': tpl['id']},
    )
    meeting = await _task(client, project['id'], 'Weekly', work_item_type='meeting')
    assert meeting['checklist_total'] == 2


async def test_approvals_on_items(client: httpx.AsyncClient, test_org):
    project = await _project(client)
    task = await _task(client, project['id'], 'Design sign-off')
    me = test_org.email
    # the requester cannot approve their own request: the step falls back to the project admins (= nobody else) → 400
    res = await client.post(
        f'{PPM}/approvals/',
        json={
            'subject_type': 'task',
            'subject_id': task['id'],
            'steps': [{'approvers': [{'type': 'user', 'ref': me}]}],
        },
    )
    assert res.status_code == 400 and res.json()['extra']['code'] == 'no_approver'

    # self-approval allowed by a policy
    res = await client.post(
        f'{PPM}/approval-policies/',
        json={
            'name': 'Self OK',
            'subject_type': 'task',
            'project_id': project['id'],
            'allow_self_approval': True,
            'steps': [
                {
                    'name': 'Lead',
                    'rule': 'any',
                    'approvers': [{'type': 'user', 'ref': me}],
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    policy = res.json()
    res = await client.post(
        f'{PPM}/approvals/',
        json={'subject_type': 'task', 'subject_id': task['id'], 'note': 'please'},
    )
    assert res.status_code == 201, res.text
    approval = res.json()
    assert (
        approval['status'] == 'pending'
        and approval['can_decide']
        and approval['approvers'][0]['user'] == me.lower()
    )
    assert (await client.get(f'{T}/{task["id"]}')).json()[
        'approval_status'
    ] == 'pending'

    # pending blocks completion; waiting for me in My Work
    res = await client.post(f'{T}/{task["id"]}/complete')
    assert res.status_code == 409 and res.json()['extra']['code'] == 'approval_pending'
    mine = (await client.get(f'{PPM}/approvals/', params={'approver': 'me'})).json()
    assert approval['id'] in {a['id'] for a in mine}
    work = (await client.get(f'{PPM}/my-work/', params={'source': 'approval'})).json()
    assert approval['id'] in {e['source_id'] for e in work.get('entries', [])}

    res = await client.post(
        f'{PPM}/approvals/{approval["id"]}/decide', json={'decision': 'rejected'}
    )
    assert res.status_code == 400 and res.json()['extra']['code'] == 'comment_required'
    res = await client.post(
        f'{PPM}/approvals/{approval["id"]}/decide',
        json={'decision': 'changes_requested', 'comment': 'fix colors'},
    )
    assert res.json()['status'] == 'changes_requested'
    res = await client.post(
        f'{PPM}/approvals/{approval["id"]}/decide', json={'decision': 'approved'}
    )
    assert res.status_code == 409 and res.json()['extra']['code'] == 'approval_closed'
    res = await client.post(f'{PPM}/approvals/{approval["id"]}/resubmit', json={})
    assert res.json()['status'] == 'pending' and res.json()['round'] == 2
    res = await client.post(
        f'{PPM}/approvals/{approval["id"]}/decide', json={'decision': 'approved'}
    )
    assert res.json()['status'] == 'approved'
    assert [e['action'] for e in res.json()['events']][:4] == [
        'requested',
        'changes_requested',
        'resubmitted',
        'approved',
    ]
    assert (await client.post(f'{T}/{task["id"]}/complete')).status_code == 200

    # an item of behaviour "approval" is done through its approval
    approval_type = (
        await client.post(
            f'{PPM}/item-types', json={'term': 'Sign-off', 'behaviour': 'approval'}
        )
    ).json()
    assert approval_type['behaviour'] == 'approval'
    gate = await _task(
        client, project['id'], 'Client sign-off', work_item_type=approval_type['key']
    )
    res = await client.post(f'{T}/{gate["id"]}/complete')
    assert res.status_code == 409 and res.json()['extra']['code'] == 'approval_required'
    res = await client.post(
        f'{PPM}/approvals/',
        json={
            'subject_type': 'task',
            'subject_id': gate['id'],
            'policy_id': policy['id'],
        },
    )
    await client.post(
        f'{PPM}/approvals/{res.json()["id"]}/decide', json={'decision': 'approved'}
    )
    assert (await client.get(f'{T}/{gate["id"]}')).json().get('completed_at')


async def test_project_templates_and_duplicate(client: httpx.AsyncClient):
    source = await _project(client, start_date='2026-10-05T00:00:00')  # a Monday
    parent = await _task(
        client,
        source['id'],
        'Kick-off',
        user_id='anna@example.com',
        start_date='2026-10-05T00:00:00',
        due_date='2026-10-09T00:00:00',
    )
    await _task(
        client,
        source['id'],
        'Agenda',
        parent_id=parent['id'],
        user_id='bob@example.com',
    )
    await client.post(f'{T}/{parent["id"]}/checklist-items', json={'name': 'Book room'})
    await client.post(f'{T}/{parent["id"]}/complete', params={'cascade': 'true'})

    res = await client.post(
        f'{P}/{source["id"]}/save-as-template',
        json={'name': 'Onboarding', 'category': 'HR'},
    )
    assert res.status_code == 201, res.text
    template = res.json()
    assert template['kind'] == 'template'
    gallery = (await client.get(f'{PPM}/project-templates/')).json()
    entry = next(t for t in gallery if t['id'] == template['id'])
    assert (
        entry['items'] == 2 and entry['category'] == 'HR' and entry['working_days'] == 5
    )
    roles = {r['name']: r['key'] for r in entry['roles']}
    assert set(roles) == {'Anna', 'Bob'}
    # templates are not regular projects
    listed = (await client.get(f'{P}/')).json()['items']
    assert template['id'] not in {p['id'] for p in listed}

    res = await client.post(
        f'{PPM}/project-templates/{template["id"]}/instantiate',
        json={
            'name': 'Onboarding Lan',
            'start_date': '2026-11-04',
            'role_map': {roles['Anna']: 'lan@example.com'},
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    tasks = (await client.get(f'{T}/', params={'project_id': created['id']})).json()[
        'items'
    ]
    kick = next(t for t in tasks if t['name'] == 'Kick-off')
    agenda = next(t for t in tasks if t['name'] == 'Agenda')
    assert (
        kick['user_id'] == 'lan@example.com' and agenda.get('user_id') is None
    )  # Bob's role left unassigned
    assert kick['start_date'].startswith('2026-11-04') and kick['due_date'].startswith(
        '2026-11-10'
    )  # +4 working days
    assert agenda['parent_id'] == kick['id'] and not kick.get('completed_at')
    assert kick['checklist_total'] == 1
    detail = (await client.get(f'{P}/{created["id"]}')).json()
    assert detail['kind'] == 'project'

    dup = (
        await client.post(f'{P}/{source["id"]}/duplicate', json={'name': 'Copy'})
    ).json()
    dup_tasks = (await client.get(f'{T}/', params={'project_id': dup['id']})).json()[
        'items'
    ]
    assert {t.get('user_id') for t in dup_tasks} == {
        'anna@example.com',
        'bob@example.com',
    }


async def test_recurring_items(client: httpx.AsyncClient):
    project = await _project(client)
    task = await _task(
        client,
        project['id'],
        'Weekly report',
        due_date='2026-10-05T00:00:00',
        recurrence_rule='FREQ=WEEKLY;BYDAY=MO;COUNT=3',
    )
    assert (
        task['recurrence_rule'] == 'FREQ=WEEKLY;BYDAY=MO;COUNT=3'
        and task['recurrence_id'] == task['id']
    )
    await client.post(
        f'{T}/{task["id"]}/checklist-items', json={'name': 'Collect numbers'}
    )
    await client.post(f'{T}/{task["id"]}/complete')
    items = (await client.get(f'{T}/', params={'project_id': project['id']})).json()[
        'items'
    ]
    nxt = next(t for t in items if t['id'] != task['id'])
    assert (
        nxt['due_date'].startswith('2026-10-12')
        and nxt['recurrence_id'] == task['id']
        and nxt['checklist_total'] == 1
    )
    await client.post(f'{T}/{nxt["id"]}/complete')
    await client.post(f'{T}/{task["id"]}/reopen')
    await client.post(
        f'{T}/{task["id"]}/complete'
    )  # a later open occurrence exists: no duplicate
    items = (await client.get(f'{T}/', params={'project_id': project['id']})).json()[
        'items'
    ]
    assert len(items) == 3  # COUNT=3 ends the series
    res = await client.patch(
        f'{T}/{task["id"]}', json={'recurrence_rule': 'FREQ=HOURLY'}
    )
    assert res.status_code == 400
