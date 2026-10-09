"""Settings of the notification service (``NOTIFICATIONS_*``, ``.env.example`` §11)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import Literal

Runner = Literal['api', 'worker', 'off']


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    runner: Runner = 'api'
    """Who sends e-mails / digests and runs scheduled app jobs: ``api`` (background task of each API process),
    ``worker`` (``ews_worker``) or ``off``."""
    interval_seconds: float = 30.0
    coalesce_seconds: int = 120
    """Instant e-mails wait this long so repeats coalesce (Ppm-1710)."""
    group_minutes: int = 10
    """Repeats of one kind on one subject within this window update one in-app row."""
    app_url: str = 'http://localhost:7101'
    """Web app base URL for e-mail links (``APP_URL``)."""


@cache
def notification_settings() -> NotificationSettings:
    runner = os.getenv('NOTIFICATIONS_RUNNER', 'api').strip().lower()
    return NotificationSettings(
        runner=runner if runner in ('api', 'worker', 'off') else 'api',  # type: ignore[arg-type]
        interval_seconds=float(os.getenv('NOTIFICATIONS_INTERVAL_SECONDS', '30') or 30),
        coalesce_seconds=int(os.getenv('NOTIFICATIONS_COALESCE_SECONDS', '120') or 120),
        app_url=(os.getenv('APP_URL') or 'http://localhost:7101').rstrip('/'),
    )
