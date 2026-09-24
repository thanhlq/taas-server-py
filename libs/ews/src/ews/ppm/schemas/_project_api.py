"""Request/response schemas for the Project API.

Kept camel-case on the wire (``ApiRequest``/``ApiResponse``) and mapped to the
``db.models.ews.Project`` SQLAlchemy model in the controller.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from db.models.ews.ews_enums import ProjectStatus
from foundation.serialization import ApiRequest, ApiResponse


class ProjectCreateRequest(ApiRequest):
    """Create a project, optionally seeded from a workflow template."""

    name: str
    description: Optional[str] = None
    code: Optional[str] = None
    status: Optional[ProjectStatus] = None
    category: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    color: Optional[str] = None
    icon_name: Optional[str] = None
    default_view: Optional[str] = None
    org_id: Optional[str] = None
    client_id: Optional[str] = None
    # Main responsible user (id / email until IAM users exist).
    user_id: Optional[str] = None
    # Free-form labels shown on the project card (stored in ``tags.labels``).
    labels: Optional[list[str]] = None
    # When set, the project's workflow is seeded from this template
    # (a ``WorkItemCategory``/methodology id, e.g. ``technology.scrum``).
    template_id: Optional[str] = None


class ProjectUpdateRequest(ApiRequest):
    """Partial update; only provided fields are applied."""

    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    status: Optional[ProjectStatus] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    color: Optional[str] = None
    icon_name: Optional[str] = None
    default_view: Optional[str] = None
    starred: Optional[bool] = None
    pinned: Optional[bool] = None
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    labels: Optional[list[str]] = None


class ProjectListItem(ApiResponse):
    """Lightweight project row for list/card views."""

    id: str
    name: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    # Badge tone of ``status`` (see ``ews.ppm._project_status``).
    status_color: Optional[str] = None
    labels: Optional[list[str]] = None
    color: Optional[str] = None
    icon_name: Optional[str] = None
    default_view: Optional[str] = None
    starred: Optional[bool] = None
    pinned: Optional[bool] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    # Main responsible user and client (CRM account id).
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    # Last change to the project or one of its tasks.
    last_activity_at: Optional[datetime] = None
    # Task progress: ``done_task_count`` / ``task_count`` as a 0-100 percentage.
    task_count: Optional[int] = None
    done_task_count: Optional[int] = None
    progress: Optional[int] = None


class ProjectResponse(ProjectListItem):
    """Full project detail."""

    org_id: Optional[str] = None
    workflow: Optional[dict[str, Any]] = None
    settings: Optional[dict[str, Any]] = None
    properties: Optional[dict[str, Any]] = None


class ProjectStatusOption(ApiResponse):
    """One entry of the project status catalog (``GET /projects/statuses``)."""

    value: str
    color: str
    group: str
