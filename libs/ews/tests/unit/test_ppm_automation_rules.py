"""PPM automation, pure part (taas-specs/ppm/automation/automation-spec.md §5B): rule validation with JSON paths,
trigger filters, conditions (current state + changes), tokens, working days, schedules, templates."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ews.ppm import _automation_rules as rules
from ews.ppm._automation_rules import Context


def rule(**over):
    base = {
        'trigger_type': 'event',
        'trigger': {'on': 'item_stage_changed', 'stage_type': 'done'},
        'conditions': [{'field': 'item.priority', 'op': 'gte', 'value': 3}],
        'actions': [
            {'type': 'create_item', 'name': 'QA: {{item.name}}', 'link': 'relates'}
        ],
    }
    return {**base, **over}


def test_valid_rules_and_templates():
    assert rules.validate(rule()) == []
    for t in rules.TEMPLATES:
        assert rules.validate(t) == [], t['key']
    assert rules.trigger_event(rule()) == 'ppm.task.updated'
    assert (
        rules.trigger_event(
            rule(trigger_type='relative', trigger={'on': 'due_in', 'days': 2})
        )
        is None
    )


def test_issues_name_the_json_path():
    bad = rule(
        trigger={'on': 'nope'},
        conditions=[
            {'field': 'item.colour', 'op': 'eq', 'value': 1},
            {'field': 'item.name', 'op': 'changed_to'},
        ],
        actions=[
            {'type': 'notify', 'recipients': [], 'message': ''},
            {'type': 'set_due', 'days': 999},
        ],
    )
    paths = {i.path for i in rules.validate(bad)}
    assert {
        'trigger.on',
        'conditions[0].field',
        'conditions[1].value',
        'actions[0].recipients',
        'actions[0].message',
        'actions[1].days',
    } <= paths
    assert {i.path for i in rules.validate(rule(actions=[]))} == {'actions'}
    schedule = rule(trigger_type='schedule', trigger={'every': 'weekly', 'at': '25:00'})
    assert {'trigger.at', 'trigger.weekday'} <= {
        i.path for i in rules.validate(schedule)
    }


def test_trigger_filters():
    stage = {'on': 'item_stage_changed', 'stage_type': 'done'}
    assert rules.trigger_matches(
        stage, {'stage_id': {'from': 'a', 'to': 'b'}}, {'stage_type': 'done'}
    )
    assert not rules.trigger_matches(
        stage, {'stage_id': {'from': 'a', 'to': 'b'}}, {'stage_type': 'in_progress'}
    )
    assert not rules.trigger_matches(
        stage, {'priority': {'from': 1, 'to': 2}}, {'stage_type': 'done'}
    )
    assert rules.trigger_matches(
        {'on': 'item_updated', 'field': 'priority'}, {'priority': {}}, {}
    )
    assert rules.trigger_matches(
        {'on': 'project_status_changed', 'status': 'At Risk'},
        {'status': {'to': 'At Risk'}},
        {},
    )


def test_conditions_read_state_and_changes():
    ctx = Context(
        item={
            'priority': 4,
            'labels': ['Backend', 'api'],
            'assignee': None,
            'due_date': '2026-10-05',
            'name': 'Payment API',
        },
        project={'status': 'Active', 'health': 'red'},
        actor='ann@example.test',
        changes={'priority': {'from': 2, 'to': 4}},
        today=date(2026, 10, 10),
    )
    checks = [
        ({'field': 'item.priority', 'op': 'gte', 'value': 3}, True),
        ({'field': 'item.priority', 'op': 'in', 'value': [1, 2]}, False),
        ({'field': 'item.labels', 'op': 'contains', 'value': 'backend'}, True),
        ({'field': 'item.labels', 'op': 'not_in', 'value': ['qa']}, True),
        ({'field': 'item.assignee', 'op': 'empty'}, True),
        ({'field': 'item.due_date', 'op': 'before', 'value': 0}, True),
        ({'field': 'item.due_date', 'op': 'after', 'value': -10}, True),
        ({'field': 'item.name', 'op': 'contains', 'value': 'payment'}, True),
        ({'field': 'project.health', 'op': 'eq', 'value': 'red'}, True),
        ({'field': 'actor', 'op': 'ne', 'value': 'ANN@example.test'}, False),
        ({'field': 'item.priority', 'op': 'changed_from', 'value': 2}, True),
        ({'field': 'item.assignee', 'op': 'changed'}, False),
    ]
    for c, expected in checks:
        assert rules.check(c, ctx) is expected, c
    ok, results = rules.evaluate([checks[0][0], checks[1][0]], ctx)
    assert not ok and [r['result'] for r in results] == [True, False]


def test_tokens_days_and_schedules():
    text = rules.render(
        'QA: {{item.name}} ({{ item.code }}) {{item.unknown}}',
        {'item.name': 'Login', 'item.code': 'P-1'},
    )
    assert text == 'QA: Login (P-1) {{item.unknown}}'
    friday = date(2026, 10, 9)
    assert rules.add_days(friday, 2, working=True) == date(2026, 10, 13)
    assert rules.add_days(friday, 2, working=False) == date(2026, 10, 11)
    assert rules.add_days(date(2026, 10, 12), -1, working=True) == date(2026, 10, 9)
    after = datetime(2026, 10, 10, 9, 30, tzinfo=UTC)  # a Saturday
    assert rules.next_run({'every': 'daily', 'at': '08:00'}, after) == datetime(
        2026, 10, 11, 8, 0, tzinfo=UTC
    )
    assert rules.next_run({'every': 'weekdays', 'at': '08:00'}, after) == datetime(
        2026, 10, 12, 8, 0, tzinfo=UTC
    )
    assert rules.next_run(
        {'every': 'weekly', 'weekday': 4, 'at': '10:00'}, after
    ) == datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    assert rules.next_run(
        {'every': 'monthly', 'day': 10, 'at': '10:00'}, after
    ) == datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
