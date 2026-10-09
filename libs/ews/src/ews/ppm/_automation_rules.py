"""Automation rules, pure part (taas-specs/ppm/automation/automation-spec.md Part B §5B, ADR-46): the V2 catalog of
triggers, condition fields / operators and actions, rule validation (issues with JSON paths), condition evaluation,
``{{token}}`` templates, the next time of a scheduled rule and the template gallery. No database."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

# --- catalog --------------------------------------------------------------------------------------

EVENT_TRIGGERS: dict[str, dict[str, Any]] = {
    'item_created': {'event': 'ppm.task.created'},
    'item_updated': {'event': 'ppm.task.updated', 'params': ('field',)},
    'item_stage_changed': {
        'event': 'ppm.task.updated',
        'params': ('stage_type', 'stage_id'),
    },
    'item_completed': {'event': 'ppm.task.completed'},
    'item_reopened': {'event': 'ppm.task.reopened'},
    'item_assigned': {'event': 'ppm.task.assigned'},
    'item_deleted': {'event': 'ppm.task.deleted'},
    'comment_added': {'event': 'ppm.comment.created'},
    'time_logged': {'event': 'ppm.time_entry.created'},
    'effort_variance': {'event': 'ppm.task.effort_variance_crossed'},
    'milestone_reached': {'event': 'ppm.milestone.reached'},
    'approval_requested': {'event': 'ppm.approval.requested'},
    'approval_approved': {'event': 'ppm.approval.approved'},
    'approval_rejected': {'event': 'ppm.approval.rejected'},
    'project_status_changed': {'event': 'ppm.project.updated', 'params': ('status',)},
    'member_added': {'event': 'ppm.project.member_added'},
}
EVENT_TOPICS = frozenset(t['event'] for t in EVENT_TRIGGERS.values())
RELATIVE_TRIGGERS = ('due_in', 'overdue_by', 'start_reached', 'no_activity')
SCHEDULES = ('daily', 'weekdays', 'weekly', 'monthly')
FOR_EACH = ('item', 'project', 'none')

ITEM_FIELDS = {
    'item.type': 'text',
    'item.behaviour': 'text',
    'item.stage_type': 'text',
    'item.stage_id': 'text',
    'item.priority': 'number',
    'item.assignee': 'user',
    'item.labels': 'list',
    'item.due_date': 'date',
    'item.start_date': 'date',
    'item.estimate': 'number',
    'item.progress': 'number',
    'item.name': 'text',
}
PROJECT_FIELDS = {'project.status': 'text', 'project.health': 'text'}
FIELDS = {**ITEM_FIELDS, **PROJECT_FIELDS, 'actor': 'user'}
OPERATORS = (
    'eq',
    'ne',
    'in',
    'not_in',
    'gt',
    'gte',
    'lt',
    'lte',
    'contains',
    'empty',
    'not_empty',
    'changed',
    'changed_to',
    'changed_from',
    'before',
    'after',
)
NO_VALUE = ('empty', 'not_empty', 'changed')
CHANGE_KEYS = {
    'item.priority': 'priority',
    'item.assignee': 'user_id',
    'item.due_date': 'due_date',
    'item.start_date': 'start_date',
    'item.stage_id': 'stage_id',
    'item.stage_type': 'stage_type',
    'item.type': 'work_item_type',
    'item.name': 'name',
    'item.estimate': 'estimated_minutes',
    'project.status': 'status',
}
"""``changes`` key of an event for the ``changed*`` operators."""

ACTIONS: dict[str, dict[str, Any]] = {
    'notify': {'undo': False},
    'create_item': {'undo': True},
    'assign': {'undo': True},
    'set_field': {'undo': True},
    'move_stage': {'undo': True},
    'set_due': {'undo': True},
    'add_checklist': {'undo': True},
    'add_comment': {'undo': False},
    'start_approval': {'undo': True},
}
SET_FIELDS = ('priority', 'estimated_minutes', 'labels_add', 'labels_remove')
RECIPIENTS = ('assignee', 'owner', 'project_admins', 'actor', 'watchers')
MAX_CONDITIONS = 20
MAX_ACTIONS = 10
TOKEN = re.compile(r'\{\{\s*([a-z_]+)\.([a-z_]+)\s*\}\}')
TOKENS = ('item.code', 'item.name', 'project.name', 'trigger.date', 'actor.name')


@dataclass(slots=True)
class Issue:
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {'path': self.path, 'message': self.message}


def _int(value: Any, low: int, high: int) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    )


def _check_trigger(kind: str, trigger: Any, out: list[Issue]) -> None:
    if not isinstance(trigger, dict):
        out.append(Issue('trigger', 'must be an object'))
        return
    if kind == 'event':
        spec = EVENT_TRIGGERS.get(trigger.get('on', ''))
        if spec is None:
            out.append(
                Issue('trigger.on', f'must be one of {", ".join(EVENT_TRIGGERS)}')
            )
    elif kind == 'relative':
        if trigger.get('on') not in RELATIVE_TRIGGERS:
            out.append(
                Issue('trigger.on', f'must be one of {", ".join(RELATIVE_TRIGGERS)}')
            )
        if trigger.get('on') != 'start_reached' and not _int(
            trigger.get('days'), 0, 365
        ):
            out.append(Issue('trigger.days', 'must be 0 to 365'))
    elif kind == 'schedule':
        if trigger.get('every') not in SCHEDULES:
            out.append(Issue('trigger.every', f'must be one of {", ".join(SCHEDULES)}'))
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(trigger.get('at', ''))):
            out.append(Issue('trigger.at', 'must be HH:MM (UTC)'))
        if trigger.get('every') == 'weekly' and not _int(trigger.get('weekday'), 0, 6):
            out.append(Issue('trigger.weekday', 'must be 0 (Monday) to 6'))
        if trigger.get('every') == 'monthly' and not _int(trigger.get('day'), 1, 28):
            out.append(Issue('trigger.day', 'must be 1 to 28'))
        if trigger.get('for_each', 'none') not in FOR_EACH:
            out.append(
                Issue('trigger.for_each', f'must be one of {", ".join(FOR_EACH)}')
            )
    else:
        out.append(Issue('trigger_type', 'must be event, relative or schedule'))


def _check_action(i: int, a: Any, out: list[Issue]) -> None:
    path = f'actions[{i}]'
    if not isinstance(a, dict) or a.get('type') not in ACTIONS:
        out.append(Issue(f'{path}.type', f'must be one of {", ".join(ACTIONS)}'))
        return
    kind = a['type']
    if kind == 'notify':
        who = a.get('recipients')
        if not isinstance(who, list) or not who:
            out.append(Issue(f'{path}.recipients', 'at least one recipient'))
        elif not all(r in RECIPIENTS or ('@' in str(r)) for r in who):
            out.append(
                Issue(
                    f'{path}.recipients', f'{", ".join(RECIPIENTS)} or e-mail addresses'
                )
            )
        if not str(a.get('message') or '').strip():
            out.append(Issue(f'{path}.message', 'a message is required'))
    elif kind == 'create_item':
        if not str(a.get('name') or '').strip():
            out.append(Issue(f'{path}.name', 'a name is required'))
        if a.get('link') not in (None, 'relates', 'blocks'):
            out.append(Issue(f'{path}.link', 'must be relates or blocks'))
        if a.get('due_in_days') is not None and not _int(a.get('due_in_days'), 0, 365):
            out.append(Issue(f'{path}.due_in_days', 'must be 0 to 365'))
    elif kind == 'assign':
        to = a.get('to')
        if not (
            to == 'actor'
            or (isinstance(to, str) and '@' in to)
            or isinstance(a.get('round_robin_role'), str)
        ):
            out.append(
                Issue(f'{path}.to', 'a user e-mail, "actor" or round_robin_role')
            )
    elif kind == 'set_field':
        if a.get('field') not in SET_FIELDS:
            out.append(
                Issue(f'{path}.field', f'must be one of {", ".join(SET_FIELDS)}')
            )
        elif a['field'] == 'priority' and not _int(a.get('value'), 0, 5):
            out.append(Issue(f'{path}.value', 'priority 0 to 5'))
        elif a['field'] == 'estimated_minutes' and not _int(
            a.get('value'), 0, 1_000_000
        ):
            out.append(Issue(f'{path}.value', 'minutes'))
        elif (
            a['field'] in ('labels_add', 'labels_remove')
            and not str(a.get('value') or '').strip()
        ):
            out.append(Issue(f'{path}.value', 'a label'))
    elif kind == 'move_stage':
        if not (a.get('stage_type') or a.get('stage_id')):
            out.append(Issue(f'{path}.stage_type', 'a stage type or a stage'))
    elif kind == 'set_due':
        if not _int(a.get('days'), -365, 365):
            out.append(Issue(f'{path}.days', 'must be -365 to 365'))
        if a.get('from', 'trigger') not in (
            'trigger',
            'today',
            'start_date',
            'due_date',
        ):
            out.append(Issue(f'{path}.from', 'trigger, today, start_date or due_date'))
    elif kind == 'add_checklist':
        if not a.get('template_id'):
            out.append(Issue(f'{path}.template_id', 'a checklist template'))
    elif kind == 'add_comment':
        if not str(a.get('text') or '').strip():
            out.append(Issue(f'{path}.text', 'a comment is required'))
    elif kind == 'start_approval':
        approvers = a.get('approvers')
        if (
            not isinstance(approvers, list)
            or not approvers
            or not all('@' in str(x) for x in approvers)
        ):
            out.append(Issue(f'{path}.approvers', 'at least one approver e-mail'))
        if a.get('rule', 'any') not in ('any', 'all'):
            out.append(Issue(f'{path}.rule', 'any or all'))


def validate(rule: dict[str, Any]) -> list[Issue]:
    """Issues of a rule JSON (``{trigger_type, trigger, conditions, actions, item_types}``); empty = valid."""
    out: list[Issue] = []
    _check_trigger(rule.get('trigger_type', ''), rule.get('trigger'), out)
    conditions = rule.get('conditions') or []
    if not isinstance(conditions, list) or len(conditions) > MAX_CONDITIONS:
        out.append(
            Issue('conditions', f'a list of at most {MAX_CONDITIONS} conditions')
        )
        conditions = []
    for i, c in enumerate(conditions):
        if not isinstance(c, dict) or c.get('field') not in FIELDS:
            out.append(
                Issue(f'conditions[{i}].field', f'must be one of {", ".join(FIELDS)}')
            )
            continue
        if c.get('op') not in OPERATORS:
            out.append(
                Issue(f'conditions[{i}].op', f'must be one of {", ".join(OPERATORS)}')
            )
        elif c['op'].startswith('changed') and c['field'] not in CHANGE_KEYS:
            out.append(
                Issue(f'conditions[{i}].op', 'this field has no change to compare')
            )
        elif c['op'] in ('before', 'after') and not _int(c.get('value'), -365, 365):
            out.append(Issue(f'conditions[{i}].value', 'days from today (-365 to 365)'))
        elif c['op'] not in NO_VALUE and 'value' not in c:
            out.append(Issue(f'conditions[{i}].value', 'a value is required'))
    actions = rule.get('actions')
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        out.append(Issue('actions', f'1 to {MAX_ACTIONS} actions'))
    else:
        for i, a in enumerate(actions):
            _check_action(i, a, out)
    types = rule.get('item_types')
    if types is not None and (
        not isinstance(types, list) or not all(isinstance(t, str) for t in types)
    ):
        out.append(Issue('item_types', 'a list of item type keys'))
    return out


def trigger_event(rule: dict[str, Any]) -> str | None:
    if rule.get('trigger_type') != 'event':
        return None
    spec = EVENT_TRIGGERS.get((rule.get('trigger') or {}).get('on', ''))
    return spec['event'] if spec else None


# --- matching and conditions ----------------------------------------------------------------------


def trigger_matches(
    trigger: dict[str, Any], changes: dict[str, Any] | None, item: dict[str, Any] | None
) -> bool:
    """The trigger's own filters: field changed, stage (type) reached, project status changed."""
    on = trigger.get('on')
    changes = changes or {}
    if on == 'item_updated' and trigger.get('field'):
        return trigger['field'] in changes
    if on == 'item_stage_changed':
        if 'stage_id' not in changes:
            return False
        if trigger.get('stage_id'):
            return str(changes['stage_id'].get('to')) == str(trigger['stage_id'])
        if trigger.get('stage_type'):
            return (item or {}).get('stage_type') == trigger['stage_type']
        return True
    if on == 'project_status_changed':
        if 'status' not in changes:
            return False
        return (
            not trigger.get('status')
            or changes['status'].get('to') == trigger['status']
        )
    return True


@dataclass(slots=True)
class Context:
    """What conditions read: the subject's **current** state, the event's changes and actor."""

    item: dict[str, Any] = field(default_factory=dict)
    project: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    today: date = field(default_factory=lambda: datetime.now(UTC).date())


def _value(ctx: Context, name: str) -> Any:
    if name == 'actor':
        return ctx.actor
    group, key = name.split('.', 1)
    return (ctx.item if group == 'item' else ctx.project).get(key)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            return float(a) == float(b)
        except ValueError:
            return False
    return a == b


def check(c: dict[str, Any], ctx: Context) -> bool:
    op, wanted = c['op'], c.get('value')
    if op.startswith('changed'):
        change = ctx.changes.get(CHANGE_KEYS.get(c['field'], ''))
        if change is None:
            return False
        if op == 'changed':
            return True
        return _same(change.get('to' if op == 'changed_to' else 'from'), wanted)
    return compare(op, _value(ctx, c['field']), wanted, ctx.today)


def compare(op: str, value: Any, wanted: Any, today: date) -> bool:
    """One operator (not ``changed*``) on a value — shared with the intake form logic and routing."""
    if op == 'empty':
        return value in (None, '', [])
    if op == 'not_empty':
        return value not in (None, '', [])
    if op in ('before', 'after'):
        day = _as_date(value)
        if day is None:
            return False
        limit = today + timedelta(days=int(wanted))
        return day < limit if op == 'before' else day > limit
    if isinstance(value, list):
        values = [str(v).lower() for v in value]
        if op in ('contains', 'eq', 'in'):
            wanted_list = wanted if isinstance(wanted, list) else [wanted]
            return any(str(w).lower() in values for w in wanted_list)
        if op in ('ne', 'not_in'):
            wanted_list = wanted if isinstance(wanted, list) else [wanted]
            return not any(str(w).lower() in values for w in wanted_list)
        return False
    if op == 'eq':
        return _same(value, wanted)
    if op == 'ne':
        return not _same(value, wanted)
    if op in ('in', 'not_in'):
        inside = any(
            _same(value, w) for w in (wanted if isinstance(wanted, list) else [wanted])
        )
        return inside if op == 'in' else not inside
    if op == 'contains':
        return value is not None and str(wanted).lower() in str(value).lower()
    try:
        a, b = float(value), float(wanted)
    except TypeError, ValueError:
        a_day, b_day = _as_date(value), _as_date(wanted)
        if a_day is None or b_day is None:
            return False
        a, b = a_day.toordinal(), b_day.toordinal()
    return {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}.get(op, False)


def evaluate(
    conditions: list[dict[str, Any]], ctx: Context
) -> tuple[bool, list[dict[str, Any]]]:
    """All conditions (one AND group in V2) with each result."""
    results = [{**c, 'result': check(c, ctx)} for c in conditions]
    return all(r['result'] for r in results), results


# --- templates and schedules ----------------------------------------------------------------------


def render(template: str, values: dict[str, Any]) -> str:
    """``{{item.name}}`` → its value (unknown tokens stay as written)."""

    def one(m: re.Match[str]) -> str:
        key = f'{m.group(1)}.{m.group(2)}'
        return str(values[key]) if values.get(key) is not None else m.group(0)

    return TOKEN.sub(one, template or '')


def add_days(start: date, days: int, working: bool) -> date:
    """``start`` + ``days`` calendar days, or working days (Mon–Fri) when ``working``."""
    if not working:
        return start + timedelta(days=days)
    step = 1 if days >= 0 else -1
    out, left = start, abs(days)
    while left:
        out += timedelta(days=step)
        if out.weekday() < 5:
            left -= 1
    return out


def next_run(trigger: dict[str, Any], after: datetime) -> datetime:
    """The first scheduled instant (UTC) strictly after ``after``."""
    hour, minute = (int(x) for x in str(trigger.get('at', '09:00')).split(':'))
    every = trigger.get('every', 'daily')
    day = after.date()
    for _ in range(400):
        moment = datetime.combine(day, time(hour, minute), UTC)
        ok = (
            every == 'daily'
            or (every == 'weekdays' and day.weekday() < 5)
            or (every == 'weekly' and day.weekday() == int(trigger.get('weekday', 0)))
            or (every == 'monthly' and day.day == int(trigger.get('day', 1)))
        )
        if ok and moment > after:
            return moment
        day += timedelta(days=1)
    return after + timedelta(days=1)


TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        'key': 'qa_handoff',
        'trigger_type': 'event',
        'trigger': {'on': 'item_stage_changed', 'stage_type': 'done'},
        'conditions': [{'field': 'item.priority', 'op': 'gte', 'value': 3}],
        'actions': [
            {
                'type': 'create_item',
                'name': 'QA: {{item.name}}',
                'link': 'relates',
                'due_in_days': 2,
                'working_days': True,
            },
            {
                'type': 'notify',
                'recipients': ['project_admins'],
                'message': '{{item.code}} {{item.name}} is done: QA item created',
            },
        ],
    },
    {
        'key': 'overdue_escalation',
        'trigger_type': 'relative',
        'trigger': {'on': 'overdue_by', 'days': 3},
        'conditions': [],
        'actions': [
            {
                'type': 'notify',
                'recipients': ['project_admins', 'assignee'],
                'message': '{{item.code}} {{item.name}} is overdue by more than 3 days',
            },
            {
                'type': 'add_comment',
                'text': 'Overdue by more than 3 days — escalated to the project admins.',
            },
        ],
    },
    {
        'key': 'due_reminder',
        'trigger_type': 'relative',
        'trigger': {'on': 'due_in', 'days': 2},
        'conditions': [{'field': 'item.assignee', 'op': 'not_empty'}],
        'actions': [
            {
                'type': 'notify',
                'recipients': ['assignee'],
                'message': '{{item.code}} {{item.name}} is due in 2 days',
            }
        ],
    },
    {
        'key': 'urgent_triage',
        'trigger_type': 'event',
        'trigger': {'on': 'item_created'},
        'conditions': [{'field': 'item.priority', 'op': 'gte', 'value': 4}],
        'actions': [
            {
                'type': 'notify',
                'recipients': ['project_admins'],
                'message': 'Urgent item created: {{item.code}} {{item.name}}',
            },
        ],
    },
    {
        'key': 'weekly_overdue_digest',
        'trigger_type': 'schedule',
        'trigger': {
            'every': 'weekly',
            'weekday': 0,
            'at': '08:00',
            'for_each': 'project',
        },
        'conditions': [],
        'actions': [
            {
                'type': 'notify',
                'recipients': ['project_admins'],
                'message': 'Weekly review of {{project.name}}: check the overdue items',
            },
        ],
    },
)
TEMPLATE_BY_KEY = {t['key']: t for t in TEMPLATES}
