"""Wire types of the project bulk actions (list "⋯" → Bulk edit / delete)."""

from __future__ import annotations

import msgspec
from db.models.ews.ews_enums import ProjectStatus
from foundation.serialization import ApiRequest, ApiResponse


class PpmProjectBulkIn(ApiRequest, kw_only=True):
    ids: list[str]
    action: str
    """``delete`` · ``update``."""
    status: ProjectStatus | None = None
    user_id: str | None = None
    """Responsible user (``update``)."""
    add_labels: list[str] = msgspec.field(default_factory=list)
    remove_labels: list[str] = msgspec.field(default_factory=list)


class PpmBulkFailure(ApiResponse, kw_only=True):
    id: str
    status: int
    detail: str


class PpmBulkOut(ApiResponse, kw_only=True):
    done: list[str] = msgspec.field(default_factory=list)
    failed: list[PpmBulkFailure] = msgspec.field(default_factory=list)
