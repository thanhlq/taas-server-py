"""Pure rules of the PPM work model V2 (taas-specs/ppm/work-model/work-model-spec.md): behaviours (§5.1), recurrence
(Ppm-0890), template working days (§5.5) and custom field values (Ppm-0850…0855)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from db.models.ppm import PpmCustomField
from foundation.exceptions import ClientException

from ews.ppm import _behaviours as behaviours
from ews.ppm import _custom_fields as cf
from ews.ppm import _recurrence as rec
from ews.ppm import _templates as tpl


# --- behaviours ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('key', 'expected'),
    [
        ('milestone', 'milestone'),
        ('deliverable', 'deliverable'),
        ('risk_assessment', 'risk'),
        ('incident', 'issue'),
        ('assumption', 'assumption'),
        ('change_request', 'request'),
        ('budget_approval', 'approval'),
        ('bug', 'task'),
        (None, 'task'),
    ],
)
def test_default_behaviour_mapping(key, expected):
    assert behaviours.default_for(key) == expected


def test_progress_and_milestone_rules():
    assert behaviours.counts('task') and behaviours.counts(None)
    assert not behaviours.counts('risk') and not behaviours.counts('request')
    due = datetime(2026, 10, 9)
    out = behaviours.apply_rules(
        'milestone',
        {'start_date': datetime(2026, 10, 1), 'due_date': due, 'estimated_minutes': 90},
    )
    assert out == {'start_date': due, 'due_date': due, 'estimated_minutes': None}
    assert behaviours.apply_rules('task', {'estimated_minutes': 90}) == {
        'estimated_minutes': 90
    }


# --- recurrence -------------------------------------------------------------------------------------------


def test_recurrence_parse_and_errors():
    rule = rec.parse('RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;COUNT=5')
    assert rule == rec.Rule('WEEKLY', 2, ((0, 0), (0, 3)), None, 5, None)
    assert rec.parse(None) is None
    with pytest.raises(ClientException):
        rec.parse('FREQ=HOURLY')
    with pytest.raises(ClientException):
        rec.parse('FREQ=MONTHLY;BYMONTHDAY=40')


def test_recurrence_next_dates():
    weekly = rec.parse('FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH')
    assert rec.next_date(weekly, date(2026, 10, 5)) == date(
        2026, 10, 8
    )  # Mon → Thu same week
    assert rec.next_date(weekly, date(2026, 10, 8)) == date(
        2026, 10, 19
    )  # Thu → Mon two weeks later
    daily = rec.parse('FREQ=DAILY;INTERVAL=3;UNTIL=20261012')
    assert rec.next_date(daily, date(2026, 10, 8)) == date(2026, 10, 11)
    assert rec.next_date(daily, date(2026, 10, 11)) is None
    last_friday = rec.parse('FREQ=MONTHLY;BYDAY=-1FR')
    assert rec.next_date(last_friday, date(2026, 10, 30)) == date(2026, 11, 27)
    month_end = rec.parse('FREQ=MONTHLY;BYMONTHDAY=31')
    assert rec.next_date(month_end, date(2026, 10, 31)) == date(
        2026, 12, 31
    )  # November has no 31st
    clamp = rec.parse('FREQ=MONTHLY')
    assert rec.next_date(clamp, date(2026, 1, 31)) == date(2026, 2, 28)
    counted = rec.parse('FREQ=YEARLY;COUNT=2')
    assert rec.next_date(counted, date(2026, 3, 1), occurrence=1) == date(2027, 3, 1)
    assert rec.next_date(counted, date(2027, 3, 1), occurrence=2) is None


# --- template working days -----------------------------------------------------------------------------------


def test_working_days():
    fri, mon = date(2026, 10, 9), date(2026, 10, 12)
    assert tpl.working_days_between(fri, mon) == 1
    assert tpl.working_days_between(mon, fri) == -1
    assert tpl.working_days_between(date(2026, 10, 5), date(2026, 10, 19)) == 10
    assert tpl.add_working_days(fri, 1) == mon
    assert tpl.add_working_days(date(2026, 10, 10), 0) == mon  # Saturday start → Monday
    assert tpl.add_working_days(mon, -1) == fri


def test_template_date_shift_keeps_working_day_offsets():
    reference = date(2026, 10, 5)  # Monday
    start = date(2026, 11, 4)  # Wednesday
    moved = tpl.shift(datetime(2026, 10, 9, 15, 0), reference, start)  # Friday = day 4
    assert moved == datetime(
        2026, 11, 10, 15, 0
    )  # 4 working days after Wednesday = Tuesday
    assert tpl.shift(None, reference, start) is None


# --- custom field values -------------------------------------------------------------------------------------


def _field(type_: str, **config) -> PpmCustomField:
    return PpmCustomField(
        key='f', label='F', type=type_, config=cf.clean_config(type_, config)
    )


def test_select_options_keep_ids_and_archive_removed():
    first = cf.clean_config(
        'select', {'options': [{'label': 'Low'}, {'label': 'High'}]}
    )
    ids = [o['id'] for o in first['options']]
    renamed = cf.clean_config(
        'select', {'options': [{'id': ids[0], 'label': 'Minor'}]}, first
    )
    assert renamed['options'][0] == {**first['options'][0], 'label': 'Minor'}
    assert (
        renamed['options'][1]['id'] == ids[1]
        and renamed['options'][1]['archived'] is True
    )


def test_value_parsing_and_wire():
    money = _field('money', decimals=2, currencies=['EUR', 'USD'])
    cols = cf._parse(money, {'amount': '12500.5', 'currency': 'eur'}, None, {})
    assert cols == {'value_number': Decimal('12500.50'), 'value_currency': 'EUR'}
    assert cf.to_wire(money, cols) == {'amount': '12500.50', 'currency': 'EUR'}
    with pytest.raises(ValueError):
        cf._parse(money, {'amount': '1', 'currency': 'GBP'}, None, {})
    number = _field('number', min=0, max=10)
    assert cf.to_wire(number, cf._parse(number, '7.50', None, {})) == '7.5'
    with pytest.raises(ValueError):
        cf._parse(number, 11, None, {})
    with pytest.raises(ValueError):
        cf._parse(_field('url'), 'ftp://x', None, {})
    sel = _field('multi_select', options=[{'label': 'A'}, {'label': 'B'}])
    a, b = (o['id'] for o in sel.config['options'])
    assert cf.to_wire(sel, cf._parse(sel, [a, b, a], None, {})) == [a, b]
    with pytest.raises(ValueError):
        cf._parse(sel, ['nope'], None, {})
    day = _field('date')
    assert cf.to_wire(day, cf._parse(day, '2026-10-10', None, {})) == '2026-10-10'
    person = _field('user')
    with pytest.raises(ValueError):
        cf._parse(person, 'x@y.z', None, {'readers': {'a@b.c'}})
    assert (
        cf.to_wire(person, cf._parse(person, 'A@B.c', None, {'readers': {'a@b.c'}}))
        == 'a@b.c'
    )


def test_filter_parameters():
    assert cf.parse_filters(
        [
            ('cf_budget_gte', '10'),
            ('cf_budget_currency', 'EUR'),
            ('cf_tier', 'a,b'),
            ('q', 'x'),
        ]
    ) == {
        'budget': {'gte': '10', 'currency': 'EUR'},
        'tier': {'eq': 'a,b'},
    }
