"""Wire types of ``/api/v1/tasks/{task_id}/checklist-items`` (work-model Ppm-0830…0834)."""

from __future__ import annotations

from datetime import datetime

from foundation.serialization import ApiRequest, ApiResponse


class PpmChecklistItemOut(ApiResponse, kw_only=True):
    id: str
    task_id: str
    name: str
    is_completed: bool = False
    completed_at: datetime | None = None
    completed_by: str | None = None
    assignee_user_id: str | None = None
    due_date: datetime | None = None
    is_mandatory: bool = False
    position: int = 0


class PpmChecklistItemCreate(ApiRequest, kw_only=True):
    name: str
    assignee_user_id: str | None = None
    due_date: datetime | None = None
    is_mandatory: bool = False


class PpmChecklistItemUpdate(ApiRequest, kw_only=True):
    """Partial update (omitted / null = unchanged); ``clear`` resets ``assignee_user_id`` / ``due_date``."""

    name: str | None = None
    is_completed: bool | None = None
    assignee_user_id: str | None = None
    due_date: datetime | None = None
    is_mandatory: bool | None = None
    clear: list[str] | None = None


class PpmChecklistOrder(ApiRequest, kw_only=True):
    ids: list[str]
