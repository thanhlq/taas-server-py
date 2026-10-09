"""Intake forms, pure part (taas-specs/ppm/intake/intake-spec.md §5.2, §5.3, ADR-47): form definition validation
(fields, logic, mapping, routing), field visibility, answers (defaults, required, types), mapping to item fields, the
title template and routing (first matching rule unless ``continue``). Conditions use the automation operators
(``_automation_rules.compare``); browser and server evaluate the same JSON. No database."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from ._automation_rules import Issue, add_days, compare

FIELD_TYPES = (
    'text',
    'textarea',
    'number',
    'date',
    'select',
    'multi_select',
    'checkbox',
    'email',
    'url',
    'section',
    'static',
)
INPUT_TYPES = frozenset(FIELD_TYPES) - {'section', 'static'}
ITEM_TARGETS = (
    'name',
    'description',
    'priority',
    'start_date',
    'due_date',
    'estimated_minutes',
    'labels',
)
"""Item fields an answer may fill; ``cf_<key>`` fills a custom field of the request type."""
CONDITION_OPS = (
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
)
ROUTING_ACTIONS = (
    'set_priority',
    'assign',
    'assign_round_robin',
    'set_due',
    'add_labels',
    'set_queue',
    'accept_in_place',
)
REQUESTER_FIELDS = ('requester.email_domain', 'requester.is_member')
DEFAULT_KINDS = ('static', 'today', 'today_plus', 'current_user')
KEY = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
MAX_FIELDS = 100
MAX_RULES = 50
MAX_TEXT = 10_000
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _today() -> date:
    return datetime.now(UTC).date()


def _options(field: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in field.get('options') or [] if isinstance(o, dict)]


def _check_conditions(
    path: str,
    block: Any,
    known: set[str],
    out: list[Issue],
    extra: tuple[str, ...] = (),
) -> None:
    if block in (None, {}):
        return
    if not isinstance(block, dict) or block.get('mode', 'all') not in ('all', 'any'):
        out.append(Issue(path, 'must be {mode: all | any, conditions: [...]}'))
        return
    conditions = block.get('conditions') or []
    if not isinstance(conditions, list) or len(conditions) > 20:
        out.append(Issue(f'{path}.conditions', 'a list of at most 20 conditions'))
        return
    for i, c in enumerate(conditions):
        if not isinstance(c, dict):
            out.append(Issue(f'{path}.conditions[{i}]', 'must be an object'))
            continue
        name = str(c.get('field', ''))
        key = name.removeprefix('answers.')
        if key not in known and name not in extra:
            out.append(
                Issue(f'{path}.conditions[{i}].field', 'must be an earlier field')
            )
        if c.get('op') not in CONDITION_OPS:
            out.append(
                Issue(
                    f'{path}.conditions[{i}].op',
                    f'must be one of {", ".join(CONDITION_OPS)}',
                )
            )


def validate(definition: Any) -> list[Issue]:
    """Issues of a form definition ``{fields, title_template, routing}``; empty = valid (publishable)."""
    out: list[Issue] = []
    if not isinstance(definition, dict):
        return [Issue('definition', 'must be an object')]
    fields = definition.get('fields') or []
    if not isinstance(fields, list) or len(fields) > MAX_FIELDS:
        return [Issue('fields', f'a list of at most {MAX_FIELDS} fields')]
    seen: set[str] = set()
    targets: set[str] = set()
    inputs = 0
    for i, f in enumerate(fields):
        path = f'fields[{i}]'
        if not isinstance(f, dict):
            out.append(Issue(path, 'must be an object'))
            continue
        key, kind = str(f.get('key', '')), f.get('type')
        if not KEY.match(key) or key in seen:
            out.append(
                Issue(f'{path}.key', 'a unique snake_case key (letters, digits, _)')
            )
        if kind not in FIELD_TYPES:
            out.append(
                Issue(f'{path}.type', f'must be one of {", ".join(FIELD_TYPES)}')
            )
            continue
        if kind in INPUT_TYPES:
            inputs += 1
            if not str(f.get('label') or '').strip():
                out.append(Issue(f'{path}.label', 'a label is required'))
        if kind in ('select', 'multi_select'):
            ids = [str(o.get('id', '')) for o in _options(f)]
            if not ids or len(set(ids)) != len(ids) or not all(ids):
                out.append(Issue(f'{path}.options', 'options with unique ids'))
        target = f.get('map')
        if target:
            if kind not in INPUT_TYPES or not (
                target in ITEM_TARGETS or str(target).startswith('cf_')
            ):
                out.append(
                    Issue(
                        f'{path}.map', f'one of {", ".join(ITEM_TARGETS)} or cf_<key>'
                    )
                )
            elif target in targets:
                out.append(Issue(f'{path}.map', 'a target is used once'))
            targets.add(str(target))
        default = f.get('default')
        if default is not None and (
            not isinstance(default, dict) or default.get('kind') not in DEFAULT_KINDS
        ):
            out.append(
                Issue(f'{path}.default', f'kind one of {", ".join(DEFAULT_KINDS)}')
            )
        _check_conditions(f'{path}.show_if', f.get('show_if'), seen, out)
        seen.add(key)
    if inputs == 0:
        out.append(Issue('fields', 'at least one question'))
    routing = definition.get('routing') or []
    if not isinstance(routing, list) or len(routing) > MAX_RULES:
        out.append(Issue('routing', f'a list of at most {MAX_RULES} rules'))
        routing = []
    for i, r in enumerate(routing):
        path = f'routing[{i}]'
        if not isinstance(r, dict):
            out.append(Issue(path, 'must be an object'))
            continue
        _check_conditions(
            path,
            {'mode': r.get('mode', 'all'), 'conditions': r.get('conditions') or []},
            seen,
            out,
            REQUESTER_FIELDS,
        )
        actions = r.get('actions') or []
        if not isinstance(actions, list) or not actions:
            out.append(Issue(f'{path}.actions', 'at least one action'))
            continue
        for j, a in enumerate(actions):
            if not isinstance(a, dict) or a.get('type') not in ROUTING_ACTIONS:
                out.append(
                    Issue(
                        f'{path}.actions[{j}].type',
                        f'must be one of {", ".join(ROUTING_ACTIONS)}',
                    )
                )
    return out


def _condition(
    c: dict[str, Any], answers: dict[str, Any], requester: dict[str, Any], today: date
) -> bool:
    name = str(c.get('field', ''))
    value = (
        requester.get(name.removeprefix('requester.'))
        if name.startswith('requester.')
        else answers.get(name.removeprefix('answers.'))
    )
    return compare(str(c.get('op')), value, c.get('value'), today)


def holds(
    block: dict[str, Any] | None,
    answers: dict[str, Any],
    requester: dict[str, Any] | None = None,
) -> bool:
    if not block or not block.get('conditions'):
        return True
    results = [
        _condition(c, answers, requester or {}, _today()) for c in block['conditions']
    ]
    return all(results) if block.get('mode', 'all') == 'all' else any(results)


def visible_keys(fields: list[dict[str, Any]], answers: dict[str, Any]) -> set[str]:
    """Keys shown for these answers: a hidden section hides its fields until the next section."""
    out: set[str] = set()
    section_shown = True
    for f in fields:
        shown = holds(f.get('show_if'), answers)
        if f.get('type') == 'section':
            section_shown = shown
            continue
        if section_shown and shown:
            out.add(f['key'])
    return out


def _default(f: dict[str, Any], member: str | None, today: date) -> Any:
    d = f.get('default') or {}
    kind = d.get('kind')
    if kind == 'static':
        return d.get('value')
    if kind == 'today':
        return today.isoformat()
    if kind == 'today_plus':
        return add_days(
            today, int(d.get('days') or 0), bool(d.get('working_days'))
        ).isoformat()
    if kind == 'current_user':
        return member
    return None


def _coerce(f: dict[str, Any], value: Any) -> tuple[Any, str | None]:
    """``(clean value, error code)``."""
    kind = f['type']
    if kind in ('text', 'textarea', 'email', 'url'):
        text = str(value).strip()
        if len(text) > (MAX_TEXT if kind == 'textarea' else 1000):
            return None, 'too_long'
        if kind == 'email' and not EMAIL.match(text):
            return None, 'invalid_email'
        if kind == 'url' and not text.startswith(('https://', 'http://')):
            return None, 'invalid_url'
        return text, None
    if kind == 'number':
        try:
            number = float(value)
        except TypeError, ValueError:
            return None, 'invalid_number'
        if (
            f.get('min') is not None
            and number < float(f['min'])
            or f.get('max') is not None
            and number > float(f['max'])
        ):
            return None, 'out_of_range'
        return int(number) if number.is_integer() else number, None
    if kind == 'date':
        try:
            return date.fromisoformat(str(value)[:10]).isoformat(), None
        except ValueError:
            return None, 'invalid_date'
    if kind == 'select':
        ids = {str(o['id']) for o in _options(f)}
        return (str(value), None) if str(value) in ids else (None, 'invalid_option')
    if kind == 'multi_select':
        ids = {str(o['id']) for o in _options(f)}
        values = [str(v) for v in (value if isinstance(value, list) else [value])]
        return (
            (values, None)
            if all(v in ids for v in values)
            else (None, 'invalid_option')
        )
    if kind == 'checkbox':
        return bool(value), None
    return None, None


def clean_answers(
    definition: dict[str, Any],
    raw: Any,
    *,
    member: str | None = None,
    today: date | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Answers of the visible fields (defaults filled, types checked) and the errors ``[{field, code}]``."""
    today = today or _today()
    fields = [f for f in definition.get('fields') or [] if isinstance(f, dict)]
    given = raw if isinstance(raw, dict) else {}
    answers: dict[str, Any] = {}
    for f in fields:
        if f.get('type') not in INPUT_TYPES:
            continue
        value = given.get(f['key'])
        if value in (None, '', []) and f.get('default'):
            value = _default(f, member, today)
        if value not in (None, '', []):
            answers[f['key']] = value
    shown = visible_keys(fields, answers)
    out: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for f in fields:
        key = f.get('key')
        if f.get('type') not in INPUT_TYPES or key not in shown:
            continue
        value = answers.get(key)
        if value in (None, '', []) or (
            f['type'] == 'checkbox' and value is False and f.get('required')
        ):
            if f.get('required'):
                errors.append({'field': key, 'code': 'required'})
            continue
        clean, error = _coerce(f, value)
        if error:
            errors.append({'field': key, 'code': error})
        else:
            out[key] = clean
    return out, errors


def _label(f: dict[str, Any], option_id: str) -> str:
    for o in _options(f):
        if str(o.get('id')) == option_id:
            return str(o.get('label') or option_id)
    return option_id


def text_of(f: dict[str, Any], value: Any) -> str:
    """An answer as text (option labels, dates ISO, booleans yes / no)."""
    if f.get('type') == 'select':
        return _label(f, str(value))
    if f.get('type') == 'multi_select':
        return ', '.join(_label(f, str(v)) for v in value or [])
    if f.get('type') == 'checkbox':
        return 'yes' if value else 'no'
    return '' if value is None else str(value)


def mapped(definition: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Item fields from the mapped answers: ``name``, ``description``, ``priority`` (0–5), dates, ``estimated_minutes``,
    ``labels`` (option labels), ``custom_fields`` (``cf_<key>``)."""
    out: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    for f in definition.get('fields') or []:
        target, key = f.get('map'), f.get('key')
        if not target or key not in answers:
            continue
        value = answers[key]
        if target.startswith('cf_'):
            custom[target.removeprefix('cf_')] = value
        elif target == 'priority':
            raw = _label(f, str(value)) if f.get('type') == 'select' else value
            try:
                out['priority'] = max(0, min(5, int(float(str(raw).split()[0]))))
            except TypeError, ValueError:
                try:
                    out['priority'] = max(0, min(5, int(str(value))))
                except ValueError:
                    continue
        elif target in ('start_date', 'due_date'):
            out[target] = f'{value}T00:00:00'
        elif target == 'estimated_minutes':
            out[target] = int(float(value))
        elif target == 'labels':
            out['labels'] = (
                [_label(f, str(v)) for v in value]
                if f.get('type') == 'multi_select'
                else [s.strip() for s in text_of(f, value).split(',') if s.strip()]
            )
        else:
            out[target] = text_of(f, value)[: 500 if target == 'name' else MAX_TEXT]
    if custom:
        out['custom_fields'] = custom
    return out


def title(
    definition: dict[str, Any],
    answers: dict[str, Any],
    *,
    form: str,
    requester: str,
    n: int,
) -> str:
    """The item name from ``title_template`` (``{form}``, ``{requester}``, ``{field:<key>}``, ``{n}``)."""
    fields = {f.get('key'): f for f in definition.get('fields') or []}
    template = str(definition.get('title_template') or '{form} — {requester}')

    def one(m: re.Match[str]) -> str:
        token = m.group(1)
        if token == 'form':
            return form
        if token == 'requester':
            return requester
        if token == 'n':
            return str(n)
        if token.startswith('field:'):
            key = token.removeprefix('field:')
            return (
                text_of(fields.get(key, {}), answers.get(key)) if key in answers else ''
            )
        return m.group(0)

    return re.sub(r'\{([a-z_:0-9]+)\}', one, template).strip()[:500] or form


def route(
    definition: dict[str, Any], answers: dict[str, Any], requester: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Routing (§5.3): the actions of the first matching rule (and of later ones while ``continue``) and the trace
    ``[{rule, name, matched}]``."""
    actions: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for i, r in enumerate(definition.get('routing') or []):
        matched = holds(
            {'mode': r.get('mode', 'all'), 'conditions': r.get('conditions') or []},
            answers,
            requester,
        )
        trace.append(
            {'rule': i, 'name': r.get('name') or f'Rule {i + 1}', 'matched': matched}
        )
        if matched:
            actions.extend(
                {**a, 'rule': i} for a in r.get('actions') or [] if isinstance(a, dict)
            )
            if not r.get('continue'):
                break
    return actions, trace


def requester_facts(email: str | None, is_member: bool) -> dict[str, Any]:
    return {
        'email_domain': (email or '').split('@')[-1].lower()
        if email and '@' in email
        else None,
        'is_member': is_member,
    }


def due_from(action: dict[str, Any], today: date | None = None) -> str:
    day = add_days(
        today or _today(),
        int(action.get('days') or 0),
        bool(action.get('working_days', True)),
    )
    return f'{day.isoformat()}T00:00:00'


STARTER: dict[str, Any] = {
    'schema_version': 1,
    'title_template': '{field:summary}',
    'fields': [
        {
            'key': 'summary',
            'type': 'text',
            'label': 'What do you need?',
            'required': True,
            'map': 'name',
        },
        {
            'key': 'request_type',
            'type': 'select',
            'label': 'Request type',
            'required': True,
            'options': [
                {'id': 'feature', 'label': 'New feature'},
                {'id': 'change', 'label': 'Change'},
                {'id': 'issue', 'label': 'Issue'},
                {'id': 'other', 'label': 'Other'},
            ],
        },
        {
            'key': 'priority',
            'type': 'select',
            'label': 'Priority',
            'options': [
                {'id': '1', 'label': '1 Low'},
                {'id': '2', 'label': '2 Normal'},
                {'id': '3', 'label': '3 High'},
                {'id': '4', 'label': '4 Urgent'},
            ],
            'default': {'kind': 'static', 'value': '2'},
            'map': 'priority',
        },
        {
            'key': 'details',
            'type': 'textarea',
            'label': 'Details',
            'map': 'description',
        },
        {
            'key': 'expected',
            'type': 'date',
            'label': 'Expected delivery',
            'map': 'due_date',
        },
    ],
    'routing': [],
}
"""The *General request* starter (the product owner's NEW REQUEST form, without CRM / money / files in V2)."""
