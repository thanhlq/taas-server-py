"""Wire types of the project health routes (taas-specs/ppm/health/project-health-spec.md §7). Ratings: ``green`` ·
``amber`` · ``red`` · ``none``; reasons carry a stable ``code`` + ``params`` the web translates."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class PpmHealthEvidenceOut(ApiResponse):
    id: str
    name: str
    code: Optional[str] = None


class PpmHealthReasonOut(ApiResponse):
    # Rule id of the spec (``S5``, ``R1``, ``C1``, ``Q2``, ``K3`` …; ``-`` = not tracked / no data).
    rule: str
    rating: str
    code: str
    params: dict[str, Any] = {}
    # Items the reason points at (≤ 10).
    evidence: list[PpmHealthEvidenceOut] = []


class PpmHealthDimensionOut(ApiResponse):
    # ``schedule`` · ``budget`` · ``resources`` · ``scope`` · ``quality`` · ``risk``.
    key: str
    rating: str
    # Worst first.
    reasons: list[PpmHealthReasonOut] = []


class PpmHealthOverrideOut(ApiResponse):
    id: str
    rating: str
    reason: str
    expires_on: date
    set_by: str
    status: str
    set_at: Optional[datetime] = None


class PpmHealthOut(ApiResponse):
    """Today's health of a project: dimensions, overall (computed) and effective (override while active)."""

    project_id: str
    snapshot_date: date
    computed_at: datetime
    overall: str
    overall_effective: str
    dimensions: list[PpmHealthDimensionOut]
    metrics: dict[str, Any] = {}
    policy_version: int = 0
    override: Optional[PpmHealthOverrideOut] = None
    # Ppm-1617: the manual project status disagrees with the health → status to suggest (``At Risk`` · ``Active``).
    status_suggestion: Optional[str] = None
    can_update: bool = False
    can_override: bool = False
    can_update_policy: bool = False


class PpmHealthDayOut(ApiResponse):
    snapshot_date: date
    overall: str
    overall_effective: str
    schedule: str
    budget: str
    resources: str
    scope: str
    quality: str
    risk: str


class PpmHealthHistoryOut(ApiResponse):
    items: list[PpmHealthDayOut]


class PpmHealthOverrideIn(ApiRequest):
    # ``green`` · ``amber`` · ``red``.
    rating: str
    # At least 10 characters.
    reason: str
    # Default today + ``override.default_days``; at most today + ``override.max_days``.
    expires_on: Optional[date] = None


class PpmHealthPolicyOut(ApiResponse):
    # Effective thresholds ``{group: {key: value}}`` (defaults ← organization ← project exception).
    thresholds: dict[str, Any]
    # Thresholds stored at this level (organization or project exception).
    own: dict[str, Any] = {}
    dimensions: list[str] = []
    # Version of this level's row (0 = none yet); send it back on PATCH.
    version: int = 0
    # Where the effective policy comes from: ``default`` · ``organization`` · ``project``.
    source: str = 'default'
    defaults: dict[str, Any] = {}
    can_update: bool = False


class PpmHealthPolicyIn(ApiRequest):
    version: int
    # Partial ``{group: {key: value}}``; ``null`` value = back to the inherited value.
    thresholds: Optional[dict[str, Any]] = None
    # Enabled dimensions (all six = every dimension).
    dimensions: Optional[list[str]] = None
