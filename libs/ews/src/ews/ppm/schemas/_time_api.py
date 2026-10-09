"""Wire types of the time tracking routes (taas-specs/ppm/time-expense/time-tracking-spec.md §7)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from foundation.serialization import ApiRequest, ApiResponse


class PpmTimeCategoryOut(ApiResponse):
    id: str
    key: str
    name: str
    # ``project`` (work on items / projects) · ``internal`` (no project).
    kind: str
    billable_allowed: bool = False
    active: bool = True


class PpmTimeEntryIn(ApiRequest):
    """A new entry: an item (``task_id``), a project, or an internal ``category``; ``minutes`` or start / end."""

    task_id: Optional[str] = None
    project_id: Optional[str] = None
    category: Optional[str] = None
    entry_date: Optional[date] = None
    minutes: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_billable: Optional[bool] = None
    description: Optional[str] = None
    # Someone else's entry (``ppm.time_entry:manage``); default the session user.
    user_id: Optional[str] = None


class PpmTimeEntryPatch(ApiRequest):
    entry_date: Optional[date] = None
    minutes: Optional[int] = None
    is_billable: Optional[bool] = None
    description: Optional[str] = None


class PpmTimeCorrectionIn(ApiRequest):
    """Reverse a locked / approved entry and, with ``minutes`` > 0, add the corrected one (§5.7)."""

    reason: str
    minutes: int = 0
    description: Optional[str] = None


class PpmTimerStartIn(ApiRequest):
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    is_billable: Optional[bool] = None
    # The person's local day (default: today, UTC).
    entry_date: Optional[date] = None


class PpmTimeEntryOut(ApiResponse):
    id: str
    user_id: Optional[str] = None
    entry_date: Optional[date] = None
    minutes: int = 0
    is_billable: bool = False
    description: Optional[str] = None
    task_id: Optional[str] = None
    task_code: Optional[str] = None
    task_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    category: Optional[str] = None
    # ``draft`` · ``submitted`` · ``approved`` · ``rejected``.
    status: str = 'draft'
    # ``manual`` · ``timer`` · ``timesheet`` · ``import`` · ``mobile``.
    source: Optional[str] = None
    # ``regular`` · ``adjustment`` (a correction, ``reverses_id``).
    kind: str = 'regular'
    reverses_id: Optional[str] = None
    correction_reason: Optional[str] = None
    timesheet_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_recording: bool = False
    needs_review: bool = False
    locked: bool = False
    editable: bool = True
    created_at: Optional[datetime] = None


class PpmEffortOut(ApiResponse):
    """E, A, R, F, V, V% of an item and of its subtree (§5.1, §5.2)."""

    estimated_minutes: int = 0
    actual_minutes: int = 0
    remaining_minutes: int = 0
    remaining_manual: bool = False
    forecast_minutes: int = 0
    variance_minutes: int = 0
    variance_pct: Optional[int] = None
    rollup_estimated_minutes: int = 0
    rollup_actual_minutes: int = 0
    rollup_remaining_minutes: int = 0
    rollup_forecast_minutes: int = 0
    rollup_variance_pct: Optional[int] = None
    # ``none`` · ``warning`` · ``critical`` (§5.8).
    variance_alert_level: str = 'none'


class PpmTimesheetCellOut(ApiResponse):
    minutes: int = 0
    entry_ids: list[str] = []


class PpmTimesheetRowOut(ApiResponse):
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    category: str = 'project'
    is_billable: bool = False
    project_name: Optional[str] = None
    task_code: Optional[str] = None
    task_name: Optional[str] = None
    # ``YYYY-MM-DD`` → the day's minutes and entries.
    cells: dict[str, PpmTimesheetCellOut] = {}
    total_minutes: int = 0


class PpmTimesheetSectionOut(ApiResponse):
    # A project id or ``internal``.
    key: str
    # Status of its approval (``pending`` · ``approved`` · ``rejected`` · ``changes_requested`` · ``cancelled``).
    status: str
    approval_id: str
    project_name: Optional[str] = None


class PpmTimesheetOut(ApiResponse):
    id: str
    user_id: str
    period_start: date
    period_end: date
    # ``open`` · ``submitted`` · ``partially_approved`` · ``approved`` · ``rejected`` · ``reopened``.
    status: str
    total_minutes: int = 0
    billable_minutes: int = 0
    expected_minutes: int = 0
    days: list[date] = []
    day_totals: list[int] = []
    rows: list[PpmTimesheetRowOut] = []
    sections: list[PpmTimesheetSectionOut] = []
    running_timer: bool = False
    editable: bool = True


class PpmTimesheetCellIn(ApiRequest):
    entry_date: date
    minutes: int
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    category: Optional[str] = None
    is_billable: Optional[bool] = None


class PpmTimesheetCellsIn(ApiRequest):
    cells: list[PpmTimesheetCellIn]


class PpmTimesheetCopyIn(ApiRequest):
    with_hours: bool = False


class PpmTimesheetRowKeyOut(ApiResponse):
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    category: str = 'project'
    is_billable: bool = False


class PpmSkippedItemOut(ApiResponse):
    task_id: str
    task_code: Optional[str] = None
    task_name: Optional[str] = None


class PpmTimesheetCopyOut(ApiResponse):
    rows: list[PpmTimesheetRowKeyOut] = []
    skipped: list[PpmSkippedItemOut] = []
    timesheet: Optional[PpmTimesheetOut] = None


class PpmTimesheetDecisionIn(ApiRequest):
    # One section (a project id or ``internal``); default every section waiting for the caller.
    section: Optional[str] = None
    note: Optional[str] = None


class PpmTimesheetReopenIn(ApiRequest):
    reason: str


class PpmTimesheetQueueItemOut(ApiResponse):
    id: str
    user_id: str
    period_start: date
    period_end: date
    status: str
    total_minutes: int = 0
    billable_minutes: int = 0
    sections: list[str] = []


class PpmTimeTotalOut(ApiResponse):
    key: str
    minutes: int = 0


class PpmProjectTimeOut(ApiResponse):
    items: list[PpmTimeEntryOut] = []
    minutes: int = 0
    billable_minutes: int = 0
    by_person: list[PpmTimeTotalOut] = []
    by_item: list[PpmTimeTotalOut] = []
