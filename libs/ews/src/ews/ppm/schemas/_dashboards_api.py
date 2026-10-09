"""Wire types of the PPM dashboards, widgets, reports and exports (taas-specs/ppm/reporting/dashboards-reports-spec.md
§7). Widget, report and series data share one shape: ``{columns: [{key, type}], rows: [[…]], total, as_of}``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class PpmWidgetTypeOut(ApiResponse):
    type: str
    sources: list[str]
    w: int
    h: int
    # Shown only while this capability is on (``health``, …).
    capability: Optional[str] = None


class PpmWidgetSourceOut(ApiResponse):
    source: str
    measures: list[str] = []
    metrics: list[str] = []
    group_by: list[str] = []


class PpmWidgetCatalogOut(ApiResponse):
    types: list[PpmWidgetTypeOut]
    sources: list[PpmWidgetSourceOut]
    filters: list[str]
    max_widgets: int = 24
    columns: int = 12


class PpmDataOut(ApiResponse):
    """Rows of a widget, report or series: ``columns[i].type`` = ``number`` · ``date`` · ``user`` · ``project`` ·
    ``rating`` · ``stage_type`` · ``hours`` · ``items`` · ``minutes`` …"""

    columns: list[dict[str, str]]
    rows: list[list[Any]]
    total: int = 0
    as_of: Optional[datetime] = None


class PpmWidgetPreviewIn(ApiRequest):
    query: dict[str, Any]
    filters: Optional[dict[str, Any]] = None
    # Project of a project dashboard (its widgets read this project).
    project_id: Optional[str] = None


class PpmDashboardItemOut(ApiResponse):
    # ``system:<key>`` for a system dashboard.
    id: str
    name: str
    scope_type: str
    scope_id: Optional[str] = None
    system_key: Optional[str] = None
    owner: Optional[str] = None
    visibility: str = 'private'
    can_edit: bool = False
    updated_at: Optional[datetime] = None


class PpmDashboardOut(ApiResponse):
    id: str
    name: str
    scope_type: str
    # ``{schema_version, widgets: [{id, type, x, y, w, h, title, query, viz, text}]}``.
    layout: dict[str, Any]
    filters: dict[str, Any] = {}
    scope_id: Optional[str] = None
    system_key: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    visibility: str = 'private'
    version: int = 0
    can_edit: bool = False
    is_owner: bool = False
    updated_at: Optional[datetime] = None


class PpmDashboardIn(ApiRequest):
    name: str
    # ``personal`` · ``project`` · ``organization``.
    scope_type: str = 'personal'
    scope_id: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[dict[str, Any]] = None
    filters: Optional[dict[str, Any]] = None
    # ``private`` · ``shared`` · ``scope``.
    visibility: str = 'private'


class PpmDashboardPatch(ApiRequest):
    version: int
    name: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[dict[str, Any]] = None
    filters: Optional[dict[str, Any]] = None
    visibility: Optional[str] = None


class PpmDashboardCopyIn(ApiRequest):
    name: Optional[str] = None
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None


class PpmDashboardShareIn(ApiRequest):
    # User reference (e-mail until IAM profiles exist).
    principal_id: str
    can_edit: bool = False


class PpmDashboardShareOut(ApiResponse):
    principal_id: str
    can_edit: bool = False


class PpmDashboardSharesIn(ApiRequest):
    shares: list[PpmDashboardShareIn]


class PpmReportOut(ApiResponse):
    key: str
    params: list[str]


class PpmReportRunIn(ApiRequest):
    params: Optional[dict[str, Any]] = None


class PpmExportIn(ApiRequest):
    """A file of a report or widget: ``csv`` · ``xlsx``; ``labels`` = translated column headers ``{key: label}``."""

    format: str
    labels: Optional[dict[str, str]] = None
    params: Optional[dict[str, Any]] = None
    filters: Optional[dict[str, Any]] = None
    project_id: Optional[str] = None
    title: Optional[str] = None
