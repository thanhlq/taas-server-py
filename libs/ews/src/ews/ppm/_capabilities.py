"""Capability levels of an organization (Ppm-0009, ADR-20): ⭐ Simple · ⭐⭐ Professional · ⭐⭐⭐ Enterprise ·
⭐⭐⭐⭐ AI-native. A level enables every capability up to it; single capabilities can be switched on or off on top
(``taas_ppm_settings.capabilities``). Disabled capabilities leave navigation, menus and views, and their API
routes answer 403 ``capability_disabled``.

Keys = the rows of taas-specs/ppm/ppm-capability-map.md. ``core`` capabilities are always on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SIMPLE, PROFESSIONAL, ENTERPRISE, AI = 1, 2, 3, 4
LEVELS = (SIMPLE, PROFESSIONAL, ENTERPRISE, AI)
DEFAULT_LEVEL = PROFESSIONAL
"""New organizations start at ⭐⭐: workflows and time logs (⭐⭐) were already in use before levels existed (ADR-34)."""


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    level: int
    core: bool = False
    """Always on (projects, tasks): cannot be switched off."""


CAPABILITIES: tuple[Capability, ...] = (
    # ⭐ Simple
    Capability('projects', SIMPLE, core=True),
    Capability('tasks', SIMPLE, core=True),
    Capability('subtasks', SIMPLE),
    Capability('checklists', SIMPLE),
    Capability('comments', SIMPLE),
    Capability('files', SIMPLE),
    Capability('my_work', SIMPLE),
    Capability('board', SIMPLE),
    Capability('calendar', SIMPLE),
    Capability('notifications', SIMPLE),
    # ⭐⭐ Professional
    Capability('workflows', PROFESSIONAL),
    Capability('iterations', PROFESSIONAL),
    Capability('gantt', PROFESSIONAL),
    Capability('dependencies', PROFESSIONAL),
    Capability('project_templates', PROFESSIONAL),
    Capability('custom_fields', PROFESSIONAL),
    Capability('item_types', PROFESSIONAL),
    Capability('intake', PROFESSIONAL),
    Capability('time_tracking', PROFESSIONAL),
    Capability('approvals', PROFESSIONAL),
    Capability('dashboards', PROFESSIONAL),
    Capability('health', PROFESSIONAL),
    Capability('automation', PROFESSIONAL),
    # ⭐⭐⭐ Enterprise
    Capability('resources', ENTERPRISE),
    Capability('critical_path', ENTERPRISE),
    Capability('baselines', ENTERPRISE),
    Capability('portfolios', ENTERPRISE),
    Capability('budgets', ENTERPRISE),
    Capability('expenses', ENTERPRISE),
    Capability('raid', ENTERPRISE),
    Capability('okr', ENTERPRISE),
    Capability('reports', ENTERPRISE),
    # ⭐⭐⭐⭐ AI-native
    Capability('ai', AI),
)
BY_KEY = {c.key: c for c in CAPABILITIES}


def effective(level: int, overrides: dict[str, Any] | None) -> dict[str, bool]:
    """``{key: enabled}`` for a level and its overrides (core capabilities always on)."""
    out: dict[str, bool] = {}
    for cap in CAPABILITIES:
        on = cap.level <= level
        value = (overrides or {}).get(cap.key)
        if isinstance(value, bool):
            on = value
        out[cap.key] = True if cap.core else on
    return out


def clean_overrides(level: int, overrides: dict[str, Any]) -> dict[str, bool]:
    """Known, non-core keys whose value differs from the level's default (so the level stays the source)."""
    out: dict[str, bool] = {}
    for key, value in overrides.items():
        cap = BY_KEY.get(key)
        if cap is None or cap.core or not isinstance(value, bool):
            continue
        if value != (cap.level <= level):
            out[key] = value
    return out
