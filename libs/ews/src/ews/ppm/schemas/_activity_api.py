"""Wire types of the Activity routes (``/api/v1/tasks/{id}/activity``, ``/api/v1/projects/{id}/activity``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import msgspec
from foundation.serialization import ApiResponse


class PpmActorOut(ApiResponse, kw_only=True):
    type: str
    """``user`` · ``rule`` · ``agent`` · ``system``."""
    ref: str | None = None
    name: str | None = None


class PpmActivityOut(ApiResponse, kw_only=True):
    id: str
    event: str
    """Topic ``ppm.<entity>.<event>`` (ADR-25)."""
    subject_type: str
    subject_id: str
    actor: PpmActorOut
    cause: str
    changes: dict[str, Any] = msgspec.field(default_factory=dict)
    """``{field: {from, to}}``."""
    data: dict[str, Any] = msgspec.field(default_factory=dict)
    occurred_at: datetime
