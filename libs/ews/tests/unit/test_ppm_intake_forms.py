"""Intake forms, pure rules (taas-specs/ppm/intake/intake-spec.md §5.2, §5.3): definition validation (Ppm-1103,
Ppm-1104), conditional logic (Ppm-1106), defaults (Ppm-1105), answers, mapping + title template, routing (Ppm-1150)."""

from __future__ import annotations

import copy
from datetime import date

from ews.ppm import _intake_forms as forms


def _definition(**extra) -> dict:
    d = copy.deepcopy(forms.STARTER)
    d.update(extra)
    return d


def test_starter_is_valid_and_issues_have_paths():
    assert forms.validate(forms.STARTER) == []
    bad = {
        'fields': [
            {'key': 'Summary', 'type': 'text', 'label': 'x'},
            {'key': 'a', 'type': 'nope'},
            {
                'key': 'b',
                'type': 'select',
                'label': 'B',
                'options': [{'id': '1'}, {'id': '1'}],
            },
            {'key': 'c', 'type': 'text', 'label': 'C', 'map': 'name'},
            {'key': 'd', 'type': 'text', 'label': 'D', 'map': 'name'},
            {
                'key': 'e',
                'type': 'text',
                'label': 'E',
                'show_if': {'conditions': [{'field': 'later', 'op': 'eq'}]},
            },
        ],
        'routing': [{'conditions': [], 'actions': [{'type': 'explode'}]}],
    }
    paths = {i.path for i in forms.validate(bad)}
    assert {
        'fields[0].key',
        'fields[1].type',
        'fields[2].options',
        'fields[4].map',
        'fields[5].show_if.conditions[0].field',
        'routing[0].actions[0].type',
    } <= paths
    assert [
        i.path
        for i in forms.validate(
            {'fields': [{'key': 's', 'type': 'section', 'label': 'S'}]}
        )
    ] == ['fields']


def test_logic_hides_fields_and_sections():
    fields = [
        {
            'key': 'kind',
            'type': 'select',
            'label': 'Kind',
            'options': [{'id': 'bug'}, {'id': 'idea'}],
        },
        {
            'key': 'steps',
            'type': 'textarea',
            'label': 'Steps',
            'required': True,
            'show_if': {
                'mode': 'all',
                'conditions': [{'field': 'kind', 'op': 'eq', 'value': 'bug'}],
            },
        },
        {
            'key': 'more',
            'type': 'section',
            'label': 'More',
            'show_if': {'conditions': [{'field': 'kind', 'op': 'eq', 'value': 'idea'}]},
        },
        {'key': 'why', 'type': 'text', 'label': 'Why', 'required': True},
    ]
    assert forms.visible_keys(fields, {'kind': 'bug'}) == {'kind', 'steps'}
    assert forms.visible_keys(fields, {'kind': 'idea'}) == {'kind', 'why'}
    # hidden fields are neither required nor stored
    answers, errors = forms.clean_answers(
        {'fields': fields}, {'kind': 'idea', 'steps': 'ignored', 'why': 'growth'}
    )
    assert answers == {'kind': 'idea', 'why': 'growth'} and errors == []
    _, errors = forms.clean_answers({'fields': fields}, {'kind': 'bug'})
    assert errors == [{'field': 'steps', 'code': 'required'}]


def test_answers_types_defaults_and_errors():
    fields = [
        {'key': 'n', 'type': 'number', 'label': 'N', 'min': 1, 'max': 10},
        {
            'key': 'd',
            'type': 'date',
            'label': 'D',
            'default': {'kind': 'today_plus', 'days': 1, 'working_days': True},
        },
        {'key': 'e', 'type': 'email', 'label': 'E'},
        {'key': 'u', 'type': 'url', 'label': 'U'},
        {
            'key': 'm',
            'type': 'multi_select',
            'label': 'M',
            'options': [{'id': 'a'}, {'id': 'b'}],
        },
        {
            'key': 'who',
            'type': 'text',
            'label': 'Who',
            'default': {'kind': 'current_user'},
        },
    ]
    friday = date(2026, 10, 9)
    answers, errors = forms.clean_answers(
        {'fields': fields}, {'n': '4', 'm': ['a', 'b']}, member='ann@x.io', today=friday
    )
    assert errors == []
    assert answers == {'n': 4, 'd': '2026-10-12', 'm': ['a', 'b'], 'who': 'ann@x.io'}
    _, errors = forms.clean_answers(
        {'fields': fields}, {'n': 20, 'e': 'nope', 'u': 'ftp://x', 'm': ['z']}
    )
    assert {e['field']: e['code'] for e in errors} == {
        'n': 'out_of_range',
        'e': 'invalid_email',
        'u': 'invalid_url',
        'm': 'invalid_option',
    }


def test_mapping_and_title_template():
    d = _definition()
    answers, _ = forms.clean_answers(
        d,
        {
            'summary': 'New laptop',
            'request_type': 'issue',
            'priority': '4',
            'expected': '2026-11-30',
        },
    )
    assert forms.mapped(d, answers) == {
        'name': 'New laptop',
        'priority': 4,
        'due_date': '2026-11-30T00:00:00',
    }
    assert (
        forms.title(d, answers, form='General request', requester='Ann', n=3)
        == 'New laptop'
    )
    d2 = _definition(title_template='{form} #{n} — {field:request_type} ({requester})')
    assert (
        forms.title(d2, answers, form='IT', requester='Ann', n=7)
        == 'IT #7 — Issue (Ann)'
    )


def test_routing_first_match_continue_and_requester_facts():
    d = _definition(
        routing=[
            {
                'name': 'Urgent',
                'conditions': [{'field': 'priority', 'op': 'eq', 'value': '4'}],
                'actions': [{'type': 'set_priority', 'value': 5}],
                'continue': True,
            },
            {
                'name': 'Partners',
                'conditions': [
                    {
                        'field': 'requester.email_domain',
                        'op': 'eq',
                        'value': 'partner.io',
                    }
                ],
                'actions': [{'type': 'assign', 'to': 'pm@x.io'}],
            },
            {
                'name': 'Fallback',
                'conditions': [],
                'actions': [{'type': 'add_labels', 'labels': ['triage']}],
            },
        ]
    )
    facts = forms.requester_facts('bob@Partner.io', False)
    assert facts == {'email_domain': 'partner.io', 'is_member': False}
    actions, trace = forms.route(d, {'priority': '4'}, facts)
    assert [a['type'] for a in actions] == ['set_priority', 'assign']
    assert [a['rule'] for a in actions] == [0, 1]
    assert [t['matched'] for t in trace] == [
        True,
        True,
    ]  # stops after the first match without continue
    actions, trace = forms.route(
        d, {'priority': '2'}, forms.requester_facts('ann@x.io', True)
    )
    assert [a['type'] for a in actions] == ['add_labels'] and [
        t['matched'] for t in trace
    ] == [False, False, True]
