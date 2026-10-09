"""Effort numbers (taas-specs/ppm/time-expense/time-tracking-spec.md §5.1–§5.3, §5.8; Ppm-1203 · 1204 · 1205)."""

from __future__ import annotations

from ews.ppm._effort import Effort, band, crossed, own, rollup, round_minutes

H = 60


def test_spec_example_manual_and_auto_remaining():
    """§5.1 "Implement Payment API": E 16h, A 21h."""
    manual = own(16 * H, 21 * H, remaining_typed=4 * H, remaining_base=21 * H)
    assert (manual.remaining, manual.forecast, manual.variance) == (4 * H, 25 * H, 9 * H)
    assert manual.variance_pct == 56 and manual.manual
    auto = own(16 * H, 21 * H)
    assert (auto.remaining, auto.forecast, auto.variance_pct) == (0, 21 * H, 31)


def test_manual_remaining_decreases_with_later_entries_and_is_zero_when_done():
    typed = own(10 * H, 2 * H, remaining_typed=5 * H, remaining_base=2 * H)
    assert typed.remaining == 5 * H
    later = own(10 * H, 4 * H, remaining_typed=5 * H, remaining_base=2 * H)
    assert later.remaining == 3 * H
    assert own(10 * H, 20 * H, remaining_typed=5 * H, remaining_base=2 * H).remaining == 0
    assert own(10 * H, 4 * H, done=True).remaining == 0
    assert own(None, 30).variance_pct is None


def test_rollup_recomputes_variance():
    """§5.2: parent E 0; children 16h / 8h, A 21h / 2h, R 4h / 6h → E 24h, F 33h, +38%."""
    a = own(16 * H, 21 * H, remaining_typed=4 * H, remaining_base=21 * H)
    b = own(8 * H, 2 * H)
    total = rollup(own(0, 0), [a, b])
    assert (total.estimate, total.forecast, total.variance_pct) == (24 * H, 33 * H, 38)


def test_bands_with_hysteresis():
    assert band(31, 20, 50) == 'warning' and band(56, 20, 50) == 'critical'
    assert band(47, 20, 50, 'critical') == 'critical'  # within 5 points: stays
    assert band(44, 20, 50, 'critical') == 'warning'
    assert band(16, 20, 50, 'warning') == 'warning' and band(14, 20, 50, 'warning') == 'none'
    assert crossed('warning', 'critical') and not crossed('critical', 'warning')
    assert band(None, 20, 50) == 'none'


def test_timer_rounding():
    assert round_minutes(7 * 60, 'up:6') == 12
    assert round_minutes(6 * 60, 'up:6') == 6
    assert round_minutes(8 * 60, 'nearest:15') == 15 and round_minutes(7 * 60, 'nearest:15') == 15
    assert round_minutes(89, 'none') == 1 and round_minutes(91, 'none') == 2
    assert round_minutes(5, 'none') == 1


def test_effort_is_a_value():
    assert Effort(60, 30, 30).forecast == 60
