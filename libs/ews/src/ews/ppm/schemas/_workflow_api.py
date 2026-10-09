"""Request/response schemas for workflow templates, stage types, project workflows and stages."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from foundation.serialization import ApiRequest, ApiResponse

# ── Catalog ───────────────────────────────────────────────────────────────────


class StageTypeResponse(ApiResponse):
    key: str
    # initial | active | review | done | special
    band: str
    order: int
    # Badge tone (gray, blue, amber, green, red, purple, teal).
    tone: str
    # Left out of progress (cancelled, rejected).
    excluded_from_progress: bool = False


class WorkItemTypeItem(ApiResponse):
    key: str
    term: str
    # work | development | issues | process | documentation | quality | requests | communication | domain
    group: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class TemplateStage(ApiResponse):
    name: str
    stage_type: str
    color: Optional[str] = None
    is_default: Optional[bool] = None


class TemplateSummary(ApiResponse):
    id: str
    category: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    workflow_type: Optional[str] = None
    stage_names: list[str] = []
    work_item_type_count: int = 0


class TemplateCategoryResponse(ApiResponse):
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    order: int = 0
    templates: list[TemplateSummary] = []


class TemplateDetail(TemplateSummary):
    work_item_types: list[WorkItemTypeItem] = []
    allowed_stage_types: list[str] = []
    stages: list[TemplateStage] = []
    # Every stage name the template suggests (for "Add stage").
    stage_suggestions: list[TemplateStage] = []


# ── Project workflows ─────────────────────────────────────────────────────────


class WorkflowStageResponse(ApiResponse):
    id: str
    workflow_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    stage_type: Optional[str] = None
    band: Optional[str] = None
    color: Optional[str] = None
    wip_limit: Optional[int] = None
    is_default: bool = False
    display_order: int = 0
    task_count: int = 0
    # Transition rules (Ppm-0201…0203): next stages allowed (empty = any), entry requirements, default assignee.
    allowed_next_stage_ids: list[str] = []
    require_assignee: bool = False
    require_due_date: bool = False
    auto_assign: bool = False
    default_assignee_id: Optional[str] = None


class WorkflowResponse(ApiResponse):
    id: str
    project_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    workflow_type: Optional[str] = None
    is_default: bool = False
    # all | assigned | team (``team_id``: members of that organization team, Ppm-0205)
    privacy: str = 'all'
    team_id: Optional[str] = None
    assigned_user_ids: list[str] = []
    # The caller is assigned to it or in its team (landing workflow).
    viewer_member: bool = False
    template_id: Optional[str] = None
    display_order: int = 0
    task_count: int = 0
    stages: list[WorkflowStageResponse] = []
    created_at: Optional[datetime] = None


class WorkflowCreateRequest(ApiRequest):
    name: str
    description: Optional[str] = None
    privacy: Optional[str] = None
    team_id: Optional[str] = None
    assigned_user_ids: Optional[list[str]] = None
    is_default: Optional[bool] = None
    # Copy the stages of this workflow (default: the template / default board).
    copy_from_workflow_id: Optional[str] = None


class WorkflowUpdateRequest(ApiRequest):
    name: Optional[str] = None
    description: Optional[str] = None
    privacy: Optional[str] = None
    team_id: Optional[str] = None
    assigned_user_ids: Optional[list[str]] = None
    # True makes it the project default (the previous default is unset).
    is_default: Optional[bool] = None


class WorkflowStageCreateRequest(ApiRequest):
    name: str
    stage_type: str
    description: Optional[str] = None
    color: Optional[str] = None
    wip_limit: Optional[int] = None
    is_default: Optional[bool] = None
    # Insert at this index (default: last).
    position: Optional[int] = None
    allowed_next_stage_ids: Optional[list[str]] = None
    require_assignee: Optional[bool] = None
    require_due_date: Optional[bool] = None
    auto_assign: Optional[bool] = None
    default_assignee_id: Optional[str] = None


class WorkflowStageUpdateRequest(ApiRequest):
    name: Optional[str] = None
    stage_type: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    wip_limit: Optional[int] = None
    is_default: Optional[bool] = None
    allowed_next_stage_ids: Optional[list[str]] = None
    require_assignee: Optional[bool] = None
    require_due_date: Optional[bool] = None
    auto_assign: Optional[bool] = None
    default_assignee_id: Optional[str] = None
    # Reset these to null: ``wip_limit``, ``description``, ``color``, ``allowed_next_stage_ids``, ``default_assignee_id``.
    clear: Optional[list[str]] = None


class WorkflowStageOrderRequest(ApiRequest):
    stage_ids: list[str]


class PpmTeamOut(ApiResponse):
    """A team of the organization (team workflows, Ppm-0205)."""

    id: str
    name: str
    member_count: int = 0
    is_member: bool = False
