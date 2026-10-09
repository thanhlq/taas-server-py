"""Project health engine (taas-specs/ppm/health/project-health-spec.md §5): rules S1–S7, R1, C1, Q1–Q3, K3, the
overall rating (ADR-23), policy thresholds and the status suggestion — pure, no database."""

from __future__ import annotations

from datetime import date

import pytest

from ews.ppm import _health_engine as engine
from ews.ppm._health_engine import Facts, Ref

ALL = frozenset(engine.DIMENSIONS)
T = engine.thresholds()


def refs(n: int) -> list[Ref]:
    return [Ref(f'id{i}', f'P-{i}', f'Item {i}') for i in range(n)]


def evaluate(f: Facts, enabled=ALL) -> engine.Health:
    return engine.evaluate(f, T, enabled)


def test_schedule_slip_matches_the_spec_example():
    # start Oct 1, due Oct 30, today Oct 19, 40 % done → 62 % elapsed, 22 points behind → 🟡
    f = Facts(
        today=date(2026, 10, 19),
        start=date(2026, 10, 1),
        due=date(2026, 10, 30),
        progress=40,
    )
    dim = evaluate(f).dimensions['schedule']
    assert dim.rating == 'amber'
    assert dim.reasons[0]['code'] == 'slip'
    assert dim.reasons[0]['params'] == {'slip': 22, 'elapsed': 62, 'progress': 40}


def test_schedule_completed_project_is_frozen_green():
    f = Facts(
        today=date(2026, 12, 1),
        due=date(2026, 10, 30),
        completed=True,
        overdue=refs(5),
        open=5,
    )
    dim = evaluate(f).dimensions['schedule']
    assert (dim.rating, [r['rule'] for r in dim.reasons]) == ('green', ['S1'])


def test_schedule_without_due_date():
    f = Facts(today=date(2026, 10, 19))
    assert evaluate(f).dimensions['schedule'].rating == 'none'
    assert evaluate(f).dimensions['schedule'].reasons[0]['code'] == 'no_due_date'
    # S7 still applies when there are open items
    f.open = 4
    assert evaluate(f).dimensions['schedule'].rating == 'green'


def test_schedule_overdue_project_and_not_started():
    late = Facts(
        today=date(2026, 11, 2),
        start=date(2026, 10, 1),
        due=date(2026, 10, 30),
        progress=90,
    )
    dim = evaluate(late).dimensions['schedule']
    assert dim.rating == 'red'
    assert dim.reasons[0]['params'] == {'days': 3}
    early = Facts(
        today=date(2026, 9, 28), start=date(2026, 10, 1), due=date(2026, 10, 30)
    )
    assert evaluate(early).dimensions['schedule'].reasons[0]['code'] == 'not_started'


def test_overdue_items_need_three_and_a_share():
    base = dict(
        today=date(2026, 10, 19),
        start=date(2026, 10, 1),
        due=date(2026, 12, 30),
        progress=30,
    )
    two = evaluate(Facts(**base, open=10, overdue=refs(2))).dimensions['schedule']
    assert [r['rating'] for r in two.reasons if r['rule'] == 'S7'] == ['green']
    three = evaluate(Facts(**base, open=10, overdue=refs(3))).dimensions['schedule']
    s7 = next(r for r in three.reasons if r['rule'] == 'S7')
    assert (s7['rating'], s7['params']['pct'], len(s7['evidence'])) == ('red', 30, 3)
    amber = evaluate(Facts(**base, open=20, overdue=refs(3))).dimensions['schedule']
    assert next(r for r in amber.reasons if r['rule'] == 'S7')['rating'] == 'amber'


def test_late_milestone_is_amber():
    f = Facts(today=date(2026, 10, 19), milestones_late=refs(1))
    dim = evaluate(f).dimensions['schedule']
    assert dim.rating == 'amber'
    assert dim.reasons[0]['code'] == 'milestones_late'


def test_resources_unassigned_due_soon():
    day = date(2026, 10, 19)
    assert (
        evaluate(Facts(today=day)).dimensions['resources'].reasons[0]['code']
        == 'no_data'
    )
    assert evaluate(Facts(today=day, open=3)).dimensions['resources'].rating == 'green'
    assert (
        evaluate(Facts(today=day, open=3, unassigned_due_soon=refs(1)))
        .dimensions['resources']
        .rating
        == 'amber'
    )
    assert (
        evaluate(Facts(today=day, open=9, unassigned_due_soon=refs(5)))
        .dimensions['resources']
        .rating
        == 'red'
    )


def test_scope_growth_against_the_reference():
    day = date(2026, 10, 19)
    grown = Facts(
        today=day, items=96, reference_items=80, reference_date=date(2026, 10, 1)
    )
    dim = evaluate(grown).dimensions['scope']
    assert dim.rating == 'amber'
    assert dim.reasons[0]['params'] == {
        'pct': 20,
        'added': 16,
        'reference': 80,
        'items': 96,
        'since': '2026-10-01',
    }
    small = Facts(today=day, items=12, reference_items=6)
    assert evaluate(small).dimensions['scope'].reasons[0]['code'] == 'no_reference'
    assert (
        evaluate(Facts(today=day, items=130, reference_items=100))
        .dimensions['scope']
        .rating
        == 'red'
    )


def test_quality_rules():
    day = date(2026, 10, 19)
    assert (
        evaluate(Facts(today=day, done_30d=4, reopened_30d=3))
        .dimensions['quality']
        .rating
        == 'none'
    )
    assert (
        evaluate(Facts(today=day, done_30d=10, reopened_30d=2))
        .dimensions['quality']
        .rating
        == 'amber'
    )
    assert (
        evaluate(Facts(today=day, done_30d=10, reopened_30d=3))
        .dimensions['quality']
        .rating
        == 'red'
    )
    defects = Facts(today=day, open=10, defects_tracked=True, open_defects=2)
    assert evaluate(defects).dimensions['quality'].rating == 'amber'
    old = Facts(
        today=day,
        open=10,
        defects_tracked=True,
        open_defects=1,
        old_critical_defects=refs(1),
    )
    dim = evaluate(old).dimensions['quality']
    assert (dim.rating, dim.reasons[0]['rule']) == ('red', 'Q3')


def test_dependency_risk():
    day = date(2026, 10, 19)
    assert evaluate(Facts(today=day)).dimensions['risk'].rating == 'none'
    assert evaluate(Facts(today=day, links=2)).dimensions['risk'].rating == 'green'
    assert (
        evaluate(Facts(today=day, links=2, dependency_risks=refs(1)))
        .dimensions['risk']
        .rating
        == 'amber'
    )


def test_overall_follows_adr_23():
    mock = {
        'schedule': 'green',
        'budget': 'amber',
        'resources': 'green',
        'scope': 'amber',
        'quality': 'green',
        'risk': 'red',
    }
    assert engine.overall(mock) == 'amber'  # one 🔴, not Schedule / Budget
    assert engine.overall({**mock, 'budget': 'red'}) == 'red'
    assert (
        engine.overall({**mock, 'risk': 'green', 'quality': 'red', 'scope': 'red'})
        == 'red'
    )
    assert engine.overall(dict.fromkeys(mock, 'none')) == 'none'
    assert engine.overall({**dict.fromkeys(mock, 'none'), 'scope': 'green'}) == 'green'


def test_disabled_dimensions_are_not_tracked():
    f = Facts(
        today=date(2026, 10, 19),
        start=date(2026, 10, 1),
        due=date(2026, 10, 2),
        progress=0,
    )
    h = evaluate(f, enabled=ALL - {'schedule'})
    assert h.dimensions['schedule'].reasons[0]['code'] == 'not_tracked'
    assert h.overall != 'red'
    assert evaluate(f).overall == 'red'


def test_policy_thresholds():
    t = engine.thresholds(
        {'schedule': {'slip_amber': 10, 'unknown': 1}}, {'schedule': {'slip_red': 20}}
    )
    assert (
        t['schedule']['slip_amber'],
        t['schedule']['slip_red'],
        t['schedule']['overdue_min'],
    ) == (10, 20, 3)
    patch = engine.clean_thresholds(
        {
            'quality': {
                'defect_types': ['Bug ', 'incident', 'bug'],
                'reopen_red_pct': None,
            }
        }
    )
    assert patch == {
        'quality': {'defect_types': ['bug', 'incident'], 'reopen_red_pct': None}
    }
    stored = engine.merge_thresholds({'quality': {'reopen_red_pct': 40}}, patch)
    assert stored == {'quality': {'defect_types': ['bug', 'incident']}}
    assert engine.merge_thresholds(stored, {'quality': {'defect_types': None}}) is None
    for bad in (
        {'schedule': {'slip_red': -1}},
        {'nope': {}},
        {'schedule': {'x': 1}},
        {'override': {'max_days': 0}},
    ):
        with pytest.raises(ValueError):
            engine.clean_thresholds(bad)
    with pytest.raises(ValueError):
        engine.check_order(engine.thresholds({'schedule': {'slip_amber': 40}}))


def test_changes_and_status_suggestion():
    assert engine.changed(None, {'schedule': 'red'}) == {}
    assert engine.changed(
        {'schedule': 'green', 'overall': 'green'},
        {'schedule': 'red', 'overall': 'green'},
    ) == {'schedule': {'from': 'green', 'to': 'red'}}
    assert engine.status_suggestion('Active', 'red') == 'At Risk'
    assert engine.status_suggestion('At Risk', 'red') is None
    assert engine.status_suggestion('Delayed', 'green') == 'Active'
    assert engine.status_suggestion('Completed', 'red') is None
