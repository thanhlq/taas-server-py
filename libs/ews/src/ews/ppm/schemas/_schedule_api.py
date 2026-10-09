"""Wire types of the schedule routes (taas-specs/ppm/schedule/schedule-spec.md §7): phases, dependency links, the
Gantt payload, schedule settings, preview and batch changes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse

# --- settings -------------------------------------------------------------------------------------


class PpmScheduleSettingsOut(ApiResponse):
    # ``manual`` (typed dates, links checked) · ``auto`` (the engine writes the dates of auto items).
    mode: str = 'manual'
    critical_float_days: int = 0
    default_duration_days: int = 1


class PpmScheduleSettingsIn(ApiRequest):
    """Partial update; null = unchanged, ``clear`` = back to the default."""

    mode: Optional[str] = None
    critical_float_days: Optional[int] = None
    default_duration_days: Optional[int] = None
    clear: Optional[list[str]] = None
    # The ``schedule_version`` the client saw (409 ``stale_schedule`` when the schedule changed meanwhile).
    base_version: Optional[int] = None


class PpmScheduleChangeOut(ApiResponse):
    """One auto item moved by the engine: ``[old, new]`` start and due."""

    task_id: str
    code: Optional[str] = None
    start: list[Optional[date]] = []
    due: list[Optional[date]] = []


class PpmSchedulePreviewOut(ApiResponse):
    changes: list[PpmScheduleChangeOut] = []
    finish: Optional[date] = None
    forecast_finish: Optional[date] = None
    cycle: Optional[list[str]] = None


class PpmScheduleSavedOut(ApiResponse):
    schedule_version: int
    settings: PpmScheduleSettingsOut
    changes: list[PpmScheduleChangeOut] = []


# --- phases ---------------------------------------------------------------------------------------


class PpmPhaseIn(ApiRequest):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    planned_start: Optional[date] = None
    planned_finish: Optional[date] = None
    clear: Optional[list[str]] = None


class PpmPhaseOrderIn(ApiRequest):
    phase_ids: list[str]


class PpmPhaseOut(ApiResponse):
    id: str
    project_id: str
    name: str
    position: float
    description: Optional[str] = None
    color: Optional[str] = None
    planned_start: Optional[date] = None
    planned_finish: Optional[date] = None
    # Items of the phase (top-level items and their subtasks).
    item_count: int = 0


class PpmSchedulePhaseOut(PpmPhaseOut):
    """A phase with its roll-up (§5.4): dates of its items (else the planned window), duration-weighted progress."""

    start: Optional[date] = None
    due: Optional[date] = None
    progress: int = 0
    # ``not_started`` · ``in_progress`` · ``done``.
    status: str = 'not_started'
    # Items outside the planned window (⚠, Ppm-1002).
    outside_window: bool = False


# --- links ----------------------------------------------------------------------------------------


class PpmItemLinkOut(ApiResponse):
    id: str
    source_task_id: str
    target_task_id: str
    source_project_id: str
    target_project_id: str
    # ``fs`` · ``ss`` · ``ff`` · ``sf`` (dependencies) · ``relates`` · ``duplicates`` · ``blocks``.
    type: str
    # Working days; negative = lead.
    lag_days: int = 0
    source_code: Optional[str] = None
    source_name: Optional[str] = None
    target_code: Optional[str] = None
    target_name: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    # Seen from the item of the route: ``predecessor`` (the other item is the source) · ``successor``.
    direction: Optional[str] = None


class PpmDependencyIn(ApiRequest):
    """A link with the item of the route: give ``predecessor_id`` (other → this) or ``successor_id`` (this → other)."""

    predecessor_id: Optional[str] = None
    successor_id: Optional[str] = None
    type: str = 'fs'
    lag_days: int = 0


class PpmDependencyUpdateIn(ApiRequest):
    type: Optional[str] = None
    lag_days: Optional[int] = None


# --- the Gantt payload ----------------------------------------------------------------------------


class PpmScheduleItemOut(ApiResponse):
    id: str
    code: Optional[str] = None
    name: Optional[str] = None
    parent_id: Optional[str] = None
    # Phase of the item's top-level ancestor (subtasks inherit).
    phase_id: Optional[str] = None
    behaviour: Optional[str] = None
    work_item_type: Optional[str] = None
    stage_type: Optional[str] = None
    user_id: Optional[str] = None
    progress: int = 0
    milestone: bool = False
    done: bool = False
    # Cancelled / rejected: out of the schedule.
    excluded: bool = False
    # Effective mode (item override, else the project's) and the item's own override.
    mode: str = 'manual'
    schedule_mode: Optional[str] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[date] = None
    started_at: Optional[date] = None
    # False = no dates, duration or link (unscheduled tray).
    scheduled: bool = True
    summary: bool = False
    # The plan (working-day duration; 0 = milestone) and the forecast at today (§5.2).
    start: Optional[date] = None
    due: Optional[date] = None
    duration: int = 0
    forecast_start: Optional[date] = None
    forecast_due: Optional[date] = None
    # Total float in working days (negative = late against the project due date) and critical flag (§5.3).
    total_float: Optional[int] = None
    critical: bool = False
    # Why this date (Ppm-1063): ``link`` (+ ``driving_link_id``) · ``constraint`` · ``manual`` · ``done`` ·
    # ``project_start`` · ``summary`` · ``unscheduled`` · ``excluded``.
    driving_link_id: Optional[str] = None
    why: str = 'none'
    # Links or constraints not met: ``{link_id, predecessor, days}`` · ``{constraint, days}`` (Ppm-1024).
    violations: list[dict[str, Any]] = []


class PpmScheduleOut(ApiResponse):
    project_id: str
    schedule_version: int
    settings: PpmScheduleSettingsOut
    project_start: date
    finish: Optional[date] = None
    forecast_finish: Optional[date] = None
    # Duration-weighted progress (Ppm-1031).
    progress: int = 0
    critical_path: list[str] = []
    # Item ids stuck in a cycle of stored links (nothing computed).
    cycle: Optional[list[str]] = None
    phases: list[PpmSchedulePhaseOut] = []
    items: list[PpmScheduleItemOut] = []
    links: list[PpmItemLinkOut] = []


# --- batch changes (Gantt drops) ------------------------------------------------------------------


class PpmScheduleItemChangeIn(ApiRequest):
    """One item of a Gantt drop; omitted = unchanged, ``clear`` resets ``phase_id`` · ``duration_days`` · constraint."""

    task_id: str
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    duration_days: Optional[int] = None
    progress: Optional[int] = None
    phase_id: Optional[str] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[datetime] = None
    clear: Optional[list[str]] = None


class PpmScheduleChangesIn(ApiRequest):
    base_version: Optional[int] = None
    changes: list[PpmScheduleItemChangeIn] = []


class PpmScheduleChangesOut(ApiResponse):
    schedule_version: int
    # Items saved from the request + auto items the engine moved.
    updated: list[str] = []
    changes: list[PpmScheduleChangeOut] = []
