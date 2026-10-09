"""Effort numbers of an item (taas-specs/ppm/time-expense/time-tracking-spec.md §5.1, §5.2, §5.8) — pure.

E = estimate · A = actual (entries not deleted, not rejected) · R = remaining (auto ``max(0, E − A)``; manual = typed −
minutes logged since it was typed, floor 0; 0 when done) · F = A + R · V = F − E · V% = V ÷ E × 100 (half-even,
``None`` without an estimate). Roll-ups add E, A, R, F of the subtree; V and V% are recomputed from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

BANDS = ('none', 'warning', 'critical')
HYSTERESIS = 5
"""An alert re-fires only after V% fell below its threshold minus these points (§5.8)."""


@dataclass(frozen=True, slots=True)
class Effort:
    estimate: int
    actual: int
    remaining: int
    manual: bool = False

    @property
    def forecast(self) -> int:
        return self.actual + self.remaining

    @property
    def variance(self) -> int:
        return self.forecast - self.estimate

    @property
    def variance_pct(self) -> int | None:
        if self.estimate <= 0:
            return None
        pct = Decimal(self.variance) * 100 / Decimal(self.estimate)
        return int(pct.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def own(
    estimate: int | None,
    actual: int | None,
    *,
    remaining_typed: int | None = None,
    remaining_base: int | None = None,
    done: bool = False,
) -> Effort:
    """One item's effort; ``remaining_base`` = its actual when the remaining was typed."""
    e, a = max(0, estimate or 0), max(0, actual or 0)
    if done:
        return Effort(e, a, 0, remaining_typed is not None)
    if remaining_typed is not None:
        logged_since = max(0, a - (remaining_base if remaining_base is not None else a))
        return Effort(e, a, max(0, remaining_typed - logged_since), True)
    return Effort(e, a, max(0, e - a))


def rollup(item: Effort, children: list[Effort]) -> Effort:
    """Own + Σ children's roll-ups (E, A, R; F follows)."""
    return Effort(
        item.estimate + sum(c.estimate for c in children),
        item.actual + sum(c.actual for c in children),
        item.remaining + sum(c.remaining for c in children),
        item.manual,
    )


def band(
    variance_pct: int | None, warning: int, critical: int, previous: str | None = None
) -> str:
    """The alert band of a variance, with hysteresis: a band stays until V% falls below its threshold − 5."""
    if variance_pct is None:
        return 'none'
    level = (
        'critical'
        if variance_pct >= critical
        else 'warning'
        if variance_pct >= warning
        else 'none'
    )
    prev = previous if previous in BANDS else 'none'
    if BANDS.index(prev) > BANDS.index(level):
        floor = critical if prev == 'critical' else warning
        if variance_pct >= floor - HYSTERESIS:
            return prev
    return level


def crossed(previous: str | None, current: str) -> bool:
    """A higher band was entered (the alert fires)."""
    prev = previous if previous in BANDS else 'none'
    return BANDS.index(current) > BANDS.index(prev)


def round_minutes(seconds: float, rule: str) -> int:
    """Timer minutes with the organization rounding (§5.3): ``none`` = half-up to the minute; ``up:<n>`` · ``nearest:<n>``."""
    minutes = Decimal(str(max(0.0, seconds))) / 60
    if rule in ('', 'none'):
        return max(1, int(minutes.quantize(Decimal(1), rounding='ROUND_HALF_UP')))
    mode, _, step_text = rule.partition(':')
    step = Decimal(int(step_text or 1))
    units = minutes / step
    rounded = units.to_integral_value(
        rounding='ROUND_CEILING' if mode == 'up' else 'ROUND_HALF_UP'
    )
    return max(int(step), int(rounded * step))
