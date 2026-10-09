"""Project health engine (taas-specs/ppm/health/project-health-spec.md §5, ADR-16 deterministic, ADR-23 overall): pure
rules → ratings, reasons and the overall rating. No database — ``_health.py`` gathers the facts.

A rule rates ``green`` / ``amber`` / ``red`` or does not apply; a dimension = its worst applicable rule, ``none`` when no
rule applies. Every reason carries a stable ``code`` + ``params`` (the web translates them) and, when it points at
items, up to ``EVIDENCE`` of them.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from typing import Any

DIMENSIONS = ('schedule', 'budget', 'resources', 'scope', 'quality', 'risk')
RATINGS = ('green', 'amber', 'red', 'none')
_WORSE = {'none': 0, 'green': 1, 'amber': 2, 'red': 3}
EVIDENCE = 10

DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    'schedule': {
        'slip_amber': 15,
        'slip_red': 30,
        'overdue_min': 3,
        'overdue_amber_pct': 10,
        'overdue_red_pct': 25,
    },
    'resources': {'unassigned_days': 14, 'unassigned_red': 5},
    'scope': {'growth_amber_pct': 10, 'growth_red_pct': 25, 'min_reference': 10},
    'quality': {
        'reopen_min_done': 5,
        'reopen_amber_pct': 10,
        'reopen_red_pct': 20,
        'defect_amber_pct': 15,
        'defect_red_pct': 30,
        'defect_age_days': 7,
        'critical_priority': 4,
        'defect_types': ['bug', 'bug_fix', 'defect'],
    },
    'override': {'default_days': 14, 'max_days': 90},
}
"""Policy defaults (§5 tables). ``defect_types`` = item type keys counted as defects (Q2 / Q3)."""

_LIMITS: dict[str, tuple[int, int]] = {
    'critical_priority': (1, 5),
    'max_days': (1, 365),
    'default_days': (1, 365),
}


@dataclass(frozen=True, slots=True)
class Ref:
    """An item a reason points at (evidence)."""

    id: str
    code: str | None
    name: str


@dataclass(slots=True)
class Facts:
    """What the rules read about one project on one day (gathered by ``_health.facts``)."""

    today: date
    start: date | None = None
    due: date | None = None
    completed: bool = False
    progress: int = 0
    items: int = 0
    """Counted items, cancelled / rejected excluded (scope)."""
    open: int = 0
    """Open counted items, milestones excluded (S7, R1, Q2)."""
    overdue: list[Ref] = field(default_factory=list)
    milestones_late: list[Ref] = field(default_factory=list)
    unassigned_due_soon: list[Ref] = field(default_factory=list)
    reference_items: int | None = None
    reference_date: date | None = None
    done_30d: int = 0
    reopened_30d: int = 0
    defects_tracked: bool = False
    open_defects: int = 0
    old_critical_defects: list[Ref] = field(default_factory=list)
    links: int = 0
    """Incoming FS / SS links into open items (K3 applies when > 0)."""
    dependency_risks: list[Ref] = field(default_factory=list)


@dataclass(slots=True)
class Dimension:
    rating: str
    reasons: list[dict[str, Any]]


@dataclass(slots=True)
class Health:
    dimensions: dict[str, Dimension]
    overall: str
    metrics: dict[str, Any]


def thresholds(*layers: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Defaults overlaid with the organization policy, then the project exception (unknown keys ignored)."""
    out = copy.deepcopy(DEFAULT_THRESHOLDS)
    for layer in layers:
        for group, values in (layer or {}).items():
            if group in out and isinstance(values, dict):
                out[group].update({k: v for k, v in values.items() if k in out[group]})
    return out


def clean_thresholds(patch: Any) -> dict[str, dict[str, Any]]:
    """A policy patch → known keys with valid values (``None`` = back to the default). Raises ``ValueError``."""
    if not isinstance(patch, dict):
        raise ValueError('thresholds must be an object {group: {key: value}}')
    out: dict[str, dict[str, Any]] = {}
    for group, values in patch.items():
        known = DEFAULT_THRESHOLDS.get(group)
        if known is None or not isinstance(values, dict):
            raise ValueError(f'unknown threshold group {group!r}')
        for key, value in values.items():
            if key not in known:
                raise ValueError(f'unknown threshold {group}.{key}')
            if value is None:
                out.setdefault(group, {})[key] = None
            elif key == 'defect_types':
                if not isinstance(value, list) or not all(
                    isinstance(v, str) and v.strip() for v in value
                ):
                    raise ValueError('defect_types must be a list of item type keys')
                out.setdefault(group, {})[key] = sorted(
                    {v.strip().lower() for v in value}
                )[:20]
            else:
                low, high = _LIMITS.get(key, (0, 1000))
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or not low <= value <= high
                ):
                    raise ValueError(
                        f'{group}.{key} must be a whole number between {low} and {high}'
                    )
                out.setdefault(group, {})[key] = value
    return out


def merge_thresholds(
    current: dict[str, Any] | None, patch: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Stored thresholds after a cleaned patch (``None`` values removed); ``None`` when nothing is left."""
    out = copy.deepcopy(current or {})
    for group, values in patch.items():
        target = out.setdefault(group, {})
        for key, value in values.items():
            if value is None:
                target.pop(key, None)
            else:
                target[key] = value
        if not target:
            out.pop(group)
    return out or None


def check_order(t: dict[str, dict[str, Any]]) -> None:
    """Amber thresholds must not be above red ones (``ValueError``)."""
    pairs = (
        ('schedule', 'slip_amber', 'slip_red'),
        ('schedule', 'overdue_amber_pct', 'overdue_red_pct'),
        ('scope', 'growth_amber_pct', 'growth_red_pct'),
        ('quality', 'reopen_amber_pct', 'reopen_red_pct'),
        ('quality', 'defect_amber_pct', 'defect_red_pct'),
    )
    for group, amber, red in pairs:
        if t[group][amber] > t[group][red]:
            raise ValueError(f'{group}.{amber} must not be above {group}.{red}')
    if t['override']['default_days'] > t['override']['max_days']:
        raise ValueError('override.default_days must not be above override.max_days')


def _reason(
    rule: str, rating: str, code: str, refs: list[Ref] | None = None, **params: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {
        'rule': rule,
        'rating': rating,
        'code': code,
        'params': params,
    }
    if refs:
        out['evidence'] = [
            {'id': r.id, 'code': r.code, 'name': r.name} for r in refs[:EVIDENCE]
        ]
    return out


def _pct(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


def _band(value: float, amber: float, red: float, *, strict: bool = True) -> str:
    """``green`` / ``amber`` / ``red``: above (``strict``) or from (not strict) each threshold."""
    if (value > red) if strict else (value >= red):
        return 'red'
    if (value > amber) if strict else (value >= amber):
        return 'amber'
    return 'green'


def schedule(f: Facts, t: dict[str, Any]) -> list[dict[str, Any]]:
    """S1–S7 (S8 baselines: V3)."""
    if f.completed:
        return [_reason('S1', 'green', 'completed')]
    out: list[dict[str, Any]] = []
    if f.due is None:
        out.append(_reason('S2', 'none', 'no_due_date'))
    elif f.today > f.due:
        out.append(_reason('S3', 'red', 'project_overdue', days=(f.today - f.due).days))
    elif f.start is not None and f.today < f.start:
        out.append(_reason('S4', 'green', 'not_started', days=(f.start - f.today).days))
    elif f.start is not None:
        span = (f.due - f.start).days
        elapsed = round((f.today - f.start).days * 100 / span) if span > 0 else 100
        slip = elapsed - f.progress
        rating = _band(slip, t['slip_amber'], t['slip_red'])
        out.append(
            _reason(
                'S5', rating, 'slip', slip=slip, elapsed=elapsed, progress=f.progress
            )
        )
    if f.milestones_late:
        out.append(
            _reason(
                'S6',
                'amber',
                'milestones_late',
                f.milestones_late,
                n=len(f.milestones_late),
            )
        )
    if f.open:
        n = len(f.overdue)
        pct = _pct(n, f.open)
        rating = (
            'green'
            if n < t['overdue_min']
            else _band(pct, t['overdue_amber_pct'], t['overdue_red_pct'], strict=False)
        )
        out.append(
            _reason('S7', rating, 'overdue_items', f.overdue, n=n, pct=pct, open=f.open)
        )
    return out


def resources(f: Facts, t: dict[str, Any]) -> list[dict[str, Any]]:
    """R1 (R2 over-allocation, R3 placeholders: V3)."""
    if not f.open:
        return []
    n = len(f.unassigned_due_soon)
    rating = 'red' if n >= t['unassigned_red'] else 'amber' if n else 'green'
    return [
        _reason(
            'R1',
            rating,
            'unassigned_due_soon',
            f.unassigned_due_soon,
            n=n,
            days=t['unassigned_days'],
        )
    ]


def scope(f: Facts, t: dict[str, Any]) -> list[dict[str, Any]]:
    """C1 against the first snapshot on or after the start date (C2 estimate growth: V3)."""
    ref = f.reference_items
    if ref is None or ref < t['min_reference']:
        return [
            _reason('C1', 'none', 'no_reference', n=ref or 0, min=t['min_reference'])
        ]
    added = f.items - ref
    pct = _pct(added, ref)
    rating = _band(pct, t['growth_amber_pct'], t['growth_red_pct'])
    since = f.reference_date.isoformat() if f.reference_date else None
    return [
        _reason(
            'C1',
            rating,
            'scope_growth',
            pct=pct,
            added=added,
            reference=ref,
            items=f.items,
            since=since,
        )
    ]


def quality(f: Facts, t: dict[str, Any]) -> list[dict[str, Any]]:
    """Q1 reopen rate, Q2 defect ratio, Q3 old critical defects."""
    out: list[dict[str, Any]] = []
    if f.done_30d >= t['reopen_min_done']:
        pct = _pct(f.reopened_30d, f.done_30d)
        rating = _band(pct, t['reopen_amber_pct'], t['reopen_red_pct'])
        out.append(
            _reason(
                'Q1',
                rating,
                'reopen_rate',
                pct=pct,
                reopened=f.reopened_30d,
                done=f.done_30d,
            )
        )
    if f.defects_tracked and f.open:
        pct = _pct(f.open_defects, f.open)
        rating = _band(pct, t['defect_amber_pct'], t['defect_red_pct'])
        out.append(
            _reason(
                'Q2', rating, 'defect_ratio', pct=pct, n=f.open_defects, open=f.open
            )
        )
    if f.old_critical_defects:
        out.append(
            _reason(
                'Q3',
                'red',
                'old_critical_defects',
                f.old_critical_defects,
                n=len(f.old_critical_defects),
                days=t['defect_age_days'],
            )
        )
    return out


def risk(f: Facts) -> list[dict[str, Any]]:
    """K3 dependency risk (K1 risks, K2 issues: V3 RAID)."""
    if not f.links:
        return []
    n = len(f.dependency_risks)
    return [
        _reason(
            'K3', 'amber' if n else 'green', 'dependency_risk', f.dependency_risks, n=n
        )
    ]


def rating_of(reasons: list[dict[str, Any]]) -> str:
    worst = 'none'
    for r in reasons:
        if _WORSE[r['rating']] > _WORSE[worst]:
            worst = r['rating']
    return worst


def overall(ratings: dict[str, str]) -> str:
    """ADR-23: 🔴 when Schedule or Budget is 🔴 or ≥ 2 dimensions are 🔴; else 🟡 when any is 🟡 / 🔴; else 🟢; all ⚪ → ⚪."""
    reds = sum(1 for r in ratings.values() if r == 'red')
    if ratings.get('schedule') == 'red' or ratings.get('budget') == 'red' or reds >= 2:
        return 'red'
    if any(r in ('amber', 'red') for r in ratings.values()):
        return 'amber'
    return 'green' if any(r == 'green' for r in ratings.values()) else 'none'


def evaluate(
    f: Facts, t: dict[str, dict[str, Any]], enabled: set[str] | frozenset[str]
) -> Health:
    """Ratings of the enabled dimensions (others ⚪ ``not_tracked``), the overall rating and the metrics."""
    rules: dict[str, list[dict[str, Any]]] = {
        'schedule': schedule(f, t['schedule']),
        'budget': [_reason('B0', 'none', 'no_budget')],
        'resources': resources(f, t['resources']),
        'scope': scope(f, t['scope']),
        'quality': quality(f, t['quality']),
        'risk': risk(f),
    }
    dims: dict[str, Dimension] = {}
    for key in DIMENSIONS:
        if key not in enabled:
            dims[key] = Dimension('none', [_reason('-', 'none', 'not_tracked')])
            continue
        reasons = sorted(rules[key], key=lambda r: -_WORSE[r['rating']])
        rating = rating_of(reasons)
        if not reasons:
            reasons = [_reason('-', 'none', 'no_data')]
        dims[key] = Dimension(rating, reasons)
    return Health(
        dimensions=dims,
        overall=overall({k: d.rating for k, d in dims.items()}),
        metrics=metrics(f),
    )


def metrics(f: Facts) -> dict[str, Any]:
    """The inputs of the rules, stored with the snapshot (``items`` = the scope reference of later days)."""
    return {
        'progress': f.progress,
        'items': f.items,
        'open': f.open,
        'overdue': len(f.overdue),
        'milestones_late': len(f.milestones_late),
        'unassigned_due_soon': len(f.unassigned_due_soon),
        'reference_items': f.reference_items,
        'reference_date': f.reference_date.isoformat() if f.reference_date else None,
        'done_30d': f.done_30d,
        'reopened_30d': f.reopened_30d,
        'open_defects': f.open_defects,
        'old_critical_defects': len(f.old_critical_defects),
        'links': f.links,
        'dependency_risks': len(f.dependency_risks),
    }


def changed(
    before: dict[str, str] | None, after: dict[str, str]
) -> dict[str, dict[str, str]]:
    """``{dimension | overall | overall_effective: {from, to}}`` of the ratings that changed (``before`` None = first)."""
    if before is None:
        return {}
    return {
        k: {'from': before.get(k, 'none'), 'to': v}
        for k, v in after.items()
        if before.get(k, 'none') != v
    }


def status_suggestion(project_status: str | None, effective: str) -> str | None:
    """Ppm-1617: the manual status disagrees with the health → the status to suggest (``At Risk`` / ``Active``)."""
    risky = {'At Risk', 'Blocked', 'Delayed'}
    if effective == 'red' and project_status not in risky | {
        'Completed',
        'Cancelled',
        'Archived',
        'On Hold',
    }:
        return 'At Risk'
    if effective == 'green' and project_status in risky:
        return 'Active'
    return None
