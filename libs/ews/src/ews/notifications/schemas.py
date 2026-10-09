"""Wire types of ``/api/v1/notifications`` (one inbox for every app, Ppm-1703 / Ppm-1706)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import msgspec
from foundation.serialization import ApiRequest, ApiResponse


class NotificationOut(ApiResponse, kw_only=True):
    id: str
    app: str
    kind: str
    title: str
    body: str | None = None
    link: str | None = None
    """Path in the web app (``/<org>/ppm/projects/<id>?task=<taskId>``)."""
    subject_type: str | None = None
    subject_id: str | None = None
    project_id: str | None = None
    actor_ref: str | None = None
    actor_name: str | None = None
    via: str = 'user'
    count: int = 1
    """Repeats batched into this row (``3 new comments on TT-40``)."""
    data: dict[str, Any] = msgspec.field(default_factory=dict)
    """Values for the reader's language text (``code``, ``name``, ``project``, ``excerpt``, …)."""
    read_at: datetime | None = None
    created_at: datetime


class NotificationCountOut(ApiResponse, kw_only=True):
    unread: int


class NotificationKindOut(ApiResponse, kw_only=True):
    key: str
    app: str
    email: str
    """Default e-mail mode: ``instant`` · ``digest`` · ``off``."""
    mandatory: bool = False


class NotificationPreferenceIn(ApiRequest, kw_only=True):
    app: str
    kind: str
    """A kind key or ``*`` (every kind of the app)."""
    channel: str
    mode: str


class NotificationPreferenceOut(ApiResponse, kw_only=True):
    app: str
    kind: str
    channel: str
    mode: str


class NotificationSettingsIo(ApiRequest, kw_only=True):
    time_zone: str = 'UTC'
    digest: str = 'daily'
    digest_hour: int = 8
    quiet_from: int | None = None
    quiet_to: int | None = None
    quiet_weekends: bool = False


class NotificationPreferencesOut(ApiResponse, kw_only=True):
    kinds: list[NotificationKindOut]
    preferences: list[NotificationPreferenceOut] = msgspec.field(default_factory=list)
    settings: NotificationSettingsIo


class NotificationPreferencesIn(ApiRequest, kw_only=True):
    """Replaces every preference of the caller (``[]`` = back to the defaults) and, when given, the settings."""

    preferences: list[NotificationPreferenceIn] = msgspec.field(default_factory=list)
    settings: NotificationSettingsIo | None = None
