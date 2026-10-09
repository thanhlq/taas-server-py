"""Schedule engine (taas-specs/ppm/schedule/schedule-spec.md §5, Ppm-1010 · 1020 · 1022 · 1023 · 1031 · 1050 · 1051
· 1061 · 1062 · 1063): working days, forward pass with FS · SS · FF · SF + lag, constraints, forecast, backward pass,
summaries, cycles, schedule progress."""

from __future__ import annotations

from datetime import date

from ews.ppm._schedule_engine import (
    Calendar,
    Item,
    Link,
    compute,
    find_cycle,
    schedule_progress,
)

MON = date(2026, 10, 5)  # p = 0 in the spec's example
FAR = date(2026, 1, 1)  # a status date before the plan: forecast = plan


def auto(id: str, duration: int | None = None, **kw) -> Item:
    return Item(id=id, duration=duration, manual=False, **kw)


def test_calendar_working_day_index():
    cal = Calendar(MON)
    assert [cal.w(date(2026, 10, d)) for d in (5, 6, 9, 10, 11, 12)] == [0, 1, 4, 5, 5, 5]
    assert cal.w(date(2026, 10, 2)) == -1 and cal.day(-1) == date(2026, 10, 2)
    assert cal.day(5) == date(2026, 10, 12) and cal.day(14) == date(2026, 10, 23)
    assert cal.working_days(date(2026, 10, 8), date(2026, 10, 13)) == 4


def test_forward_pass_spec_example():
    """§5.2: A D3 → Oct 5–7; B FS+1 D2 → Oct 9–12; C SS+1 D4 → Oct 6–9; milestone M FS from B and C → Oct 12."""
    items = [
        auto('A', 3),
        auto('B', 2),
        auto('C', 4),
        Item(id='M', milestone=True, manual=False),
    ]
    links = [
        Link('l1', 'A', 'B', 'fs', 1),
        Link('l2', 'A', 'C', 'ss', 1),
        Link('l3', 'B', 'M'),
        Link('l4', 'C', 'M'),
    ]
    s = compute(items, links, project_start=MON, today=FAR)
    r = s.items
    assert (r['A'].start, r['A'].due) == (date(2026, 10, 5), date(2026, 10, 7))
    assert (r['B'].start, r['B'].due) == (date(2026, 10, 9), date(2026, 10, 12))
    assert (r['C'].start, r['C'].due) == (date(2026, 10, 6), date(2026, 10, 9))
    assert r['M'].start == r['M'].due == date(2026, 10, 12) and r['M'].duration == 0
    # Why this date (Ppm-1063): B is driven by the FS + 1 link from A
    assert (r['B'].why, r['B'].driving_link) == ('link', 'l1')
    assert r['A'].why == 'project_start'
    # §5.3: A 0, B 0, C 1 → critical path A → B → M
    assert [r[x].total_float for x in 'ABCM'] == [0, 0, 1, 0]
    assert s.critical_path == ['A', 'B', 'M']
    assert s.finish == date(2026, 10, 12)


def test_ff_sf_and_lead():
    items = [auto('P', 3), auto('F', 2), auto('S', 2), auto('L', 2)]
    links = [
        Link('ff', 'P', 'F', 'ff'),  # F finishes with P: EF 3 → ES 1
        Link('sf', 'P', 'S', 'sf', 2),  # S finishes ≥ P.ES + 2 → ES 0
        Link('lead', 'P', 'L', 'fs', -1),  # FS − 1: starts on P's last day
    ]
    r = compute(items, links, project_start=MON, today=FAR).items
    assert (r['F'].start, r['F'].due) == (date(2026, 10, 6), date(2026, 10, 7))
    assert r['S'].start == MON
    assert r['L'].start == date(2026, 10, 7)


def test_lead_is_bounded_by_project_start():
    items = [auto('P', 1), auto('S', 1)]
    r = compute(items, [Link('l', 'P', 'S', 'ss', -5)], project_start=MON, today=FAR).items
    assert r['S'].start == MON


def test_manual_items_are_fixed_and_report_violations():
    """Ppm-1024 / 1050: a manual item keeps its dates, drives successors; a late successor is a violation."""
    items = [
        Item(id='A', start=date(2026, 10, 5), due=date(2026, 10, 9)),
        Item(id='B', start=date(2026, 10, 7), due=date(2026, 10, 8)),
        auto('C', 1),
    ]
    links = [Link('ab', 'A', 'B'), Link('ac', 'A', 'C')]
    r = compute(items, links, project_start=MON, today=FAR).items
    assert (r['B'].start, r['B'].why) == (date(2026, 10, 7), 'manual')
    assert r['B'].violations == [{'link_id': 'ab', 'predecessor': 'A', 'days': 3}]
    assert r['C'].start == date(2026, 10, 12) and r['C'].violations == []


def test_constraints_snet_mso_fnlt():
    """Ppm-1051: SNET pushes, MSO wins over a later bound (violation), FNLT flags a late finish."""
    items = [
        auto('A', 3),
        auto('S', 1, constraint='snet', constraint_date=date(2026, 10, 14)),
        auto('M', 1, constraint='mso', constraint_date=date(2026, 10, 6)),
        auto('F', 2, constraint='fnlt', constraint_date=date(2026, 10, 7)),
    ]
    links = [Link('am', 'A', 'M'), Link('af', 'A', 'F')]
    r = compute(items, links, project_start=MON, today=FAR).items
    assert (r['S'].start, r['S'].why) == (date(2026, 10, 14), 'constraint')
    assert r['M'].start == date(2026, 10, 6)
    assert r['M'].violations[0]['link_id'] == 'am'
    assert r['F'].start == date(2026, 10, 8)
    assert r['F'].violations == [{'constraint': 'fnlt', 'days': 2}]
    assert r['F'].total_float < 0


def test_forecast_pushes_late_work_and_uses_remaining_duration():
    """Ppm-1061: not started → after the status date; started → R = ceil(D × (100 − p) / 100) from today."""
    items = [
        auto('A', 4, started=date(2026, 10, 5), progress=50),
        auto('B', 2),
        Item(id='late', start=date(2026, 10, 5), due=date(2026, 10, 6)),
    ]
    s = compute(items, [Link('ab', 'A', 'B')], project_start=MON, today=date(2026, 10, 8))
    r = s.items
    assert r['A'].due == date(2026, 10, 8)  # plan unchanged
    assert r['A'].forecast_due == date(2026, 10, 9)  # Thu + 2 remaining days
    assert r['B'].forecast_start == date(2026, 10, 12)
    assert r['late'].forecast_start == date(2026, 10, 8)
    assert r['late'].start == date(2026, 10, 5)
    assert s.forecast_finish == date(2026, 10, 13)


def test_done_items_are_fixed_at_actuals_and_never_critical():
    items = [
        Item(id='D', start=date(2026, 10, 5), done=True, finished=date(2026, 10, 6)),
        auto('N', 1),
    ]
    r = compute(items, [Link('dn', 'D', 'N')], project_start=MON, today=FAR).items
    assert (r['D'].start, r['D'].due, r['D'].why) == (MON, date(2026, 10, 6), 'done')
    assert not r['D'].critical
    assert r['N'].start == date(2026, 10, 7)


def test_unscheduled_due_only_and_excluded():
    items = [
        Item(id='none'),
        Item(id='due', due=date(2026, 10, 9)),
        Item(id='x', start=date(2026, 10, 5), excluded=True),
        auto('linked'),
    ]
    r = compute(items, [Link('l', 'x', 'linked')], project_start=MON, today=FAR).items
    assert (r['none'].scheduled, r['none'].why) == (False, 'unscheduled')
    assert r['due'].start == r['due'].due == date(2026, 10, 9)
    assert (r['x'].scheduled, r['x'].why) == (False, 'excluded')
    assert r['linked'].duration == 1 and r['linked'].start == MON  # default duration, link ignored


def test_summary_rolls_up_and_its_links_apply_to_descendants():
    """Ppm-1023 / §5.4."""
    items = [
        auto('P', 2),
        Item(id='S', start=date(2026, 10, 20), due=date(2026, 10, 30)),  # own dates ignored
        auto('c1', 2, parent_id='S'),
        auto('c2', 3, parent_id='S'),
    ]
    r = compute(items, [Link('ps', 'P', 'S')], project_start=MON, today=FAR).items
    assert r['c1'].start == r['c2'].start == date(2026, 10, 7)
    assert (r['S'].start, r['S'].due, r['S'].why) == (date(2026, 10, 7), date(2026, 10, 9), 'summary')
    assert r['S'].summary and r['S'].duration == 3


def test_cycle_detection():
    """Ppm-1022: self, ancestor / descendant, a path back (also through a summary's descendants)."""
    items = {i.id: i for i in [Item('A'), Item('B'), Item('C'), Item('S'), Item('k', parent_id='S')]}
    links = [Link('ab', 'A', 'B'), Link('bc', 'B', 'C'), Link('ck', 'C', 'k')]
    assert find_cycle(items, links, Link('n', 'A', 'A')) == ['A', 'A']
    assert find_cycle(items, links, Link('n', 'S', 'k')) == ['S', 'k']
    assert find_cycle(items, links, Link('n', 'C', 'A')) == ['C', 'A', 'B', 'C']
    assert find_cycle(items, links, Link('n', 'S', 'A')) == ['S', 'A', 'B', 'C', 'k']
    assert find_cycle(items, links, Link('n', 'A', 'C')) is None
    # a cycle in stored data stops the run
    looped = compute([auto('A', 1), auto('B', 1)], [Link('1', 'A', 'B'), Link('2', 'B', 'A')])
    assert sorted(looped.cycle or []) == ['A', 'B']


def test_schedule_progress_is_duration_weighted():
    """Ppm-1031 / §5.5."""
    items = [auto('a', 1, progress=100), auto('b', 3), Item(id='m', milestone=True, due=MON)]
    r = compute(items, [], project_start=MON, today=FAR).items
    assert schedule_progress(items, r) == 25
    only_milestones = [Item(id='m1', milestone=True, due=MON, done=True), Item(id='m2', milestone=True, due=MON)]
    assert schedule_progress(only_milestones, compute(only_milestones, [], project_start=MON).items) == 50
