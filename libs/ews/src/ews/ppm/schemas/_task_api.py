"""Request/response schemas for the Task API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from foundation.serialization import ApiRequest, ApiResponse


class TaskCreateRequest(ApiRequest):
    """Create a task inside a project (optionally in a specific stage/column)."""

    project_id: str
    name: str
    description: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    parent_id: Optional[str] = None
    requested_user_id: Optional[str] = None
    progress: Optional[int] = None


class TaskUpdateRequest(ApiRequest):
    """Partial update — used by the quick-edit drawer and drag-and-drop moves."""

    name: Optional[str] = None
    description: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    progress: Optional[int] = None
    requested_user_id: Optional[str] = None


class TaskResponse(ApiResponse):
    id: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    parent_id: Optional[str] = None
    requested_user_id: Optional[str] = None
    progress: Optional[int] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
