"""Item behaviours (taas-specs/ppm/work-model/work-model-spec.md §5.1, Ppm-0803): the fixed catalog of rules an item
type carries. Pure — no database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Behaviour:
    key: str
    in_progress: bool = True
    """False: left out of item and project progress, like cancelled / rejected stages (extends Ppm-0004)."""
    single_date: bool = False
    """One date: start = due."""
    no_effort: bool = False
    """No estimate and no time."""
    done_by_approval: bool = False
    """Done only through its approval (approved → done stage, rejected → rejected / cancelled stage)."""


BEHAVIOURS: tuple[Behaviour, ...] = (
    Behaviour('task'),
    Behaviour('milestone', single_date=True, no_effort=True),
    Behaviour('deliverable'),
    Behaviour('approval', done_by_approval=True),
    Behaviour('request', in_progress=False),
    Behaviour('risk', in_progress=False),
    Behaviour('issue', in_progress=False),
    Behaviour('assumption', in_progress=False),
    Behaviour('decision', in_progress=False),
)
BY_KEY = {b.key: b for b in BEHAVIOURS}
DEFAULT = 'task'
NOT_IN_PROGRESS: frozenset[str] = frozenset(
    b.key for b in BEHAVIOURS if not b.in_progress
)


def get(key: str | None) -> Behaviour:
    return BY_KEY.get(key or DEFAULT, BY_KEY[DEFAULT])


def is_behaviour(key: Any) -> bool:
    return isinstance(key, str) and key in BY_KEY


def counts(behaviour: str | None) -> bool:
    """Whether items of this behaviour count in progress."""
    return behaviour not in NOT_IN_PROGRESS


def default_for(key: str | None) -> str:
    """Behaviour of a catalog key (§5.1 default mapping)."""
    k = (key or '').strip().lower()
    if k in ('milestone', 'deliverable', 'decision', 'assumption'):
        return k
    if k in ('risk', 'risk_assessment'):
        return 'risk'
    if k in ('issue', 'incident'):
        return 'issue'
    if k.endswith('request'):
        return 'request'
    if k.endswith('approval'):
        return 'approval'
    return DEFAULT


def apply_rules(behaviour: str | None, fields: dict[str, Any]) -> dict[str, Any]:
    """Item fields after the behaviour's rules (Ppm-0806): a milestone has one date (start = due) and no estimate.
    ``fields`` holds ``start_date``, ``due_date``, ``estimated_minutes`` (missing keys are left alone)."""
    b = get(behaviour)
    out = dict(fields)
    if b.single_date:
        day = out.get('due_date') or out.get('start_date')
        if 'due_date' in out or 'start_date' in out:
            out['start_date'] = day
            out['due_date'] = day
    if b.no_effort and 'estimated_minutes' in out:
        out['estimated_minutes'] = None
    return out
