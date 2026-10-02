"""Dead-letter queue settings from the environment (``DLQ_*``).

Same variables and defaults as ``ResiliantSettings.deadLetterConfig()`` of
``@taas/foundation`` (taas-server-js). A malformed value raises — it never falls
back to the default silently. ``DLQ_ENABLED`` / ``DLQ_TOPIC`` belong to messaging
(the broker's DLQ topic), not to this table-backed queue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from foundation.resiliant.dlq import DeadLetterConfig
from foundation.utils.env_utils import get_env

_DEFAULT = DeadLetterConfig()


def parse_handler_limits(value: str | None) -> dict[str, int]:
    """``"OrderHandler:5,Other:2"`` (or a JSON object) -> ``{'OrderHandler': 5, 'Other': 2}``.

    Raises:
        ValueError: an entry that is not ``Handler:limit`` with an integer limit >= 1.
    """
    if value is None or not value.strip():
        return {}
    if value.strip().startswith('{'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f'DLQ_HANDLER_MAX_RETRIES is not valid JSON: {value!r}') from error
        if not isinstance(parsed, dict):
            raise ValueError(f'DLQ_HANDLER_MAX_RETRIES must be a JSON object, got {value!r}')
        entries = [f'{name}:{limit}' for name, limit in parsed.items()]
    else:
        entries = [entry for entry in value.split(',') if entry.strip()]
    limits: dict[str, int] = {}
    for entry in entries:
        name, sep, raw = entry.rpartition(':')
        name = name.strip()
        try:
            limit = int(raw.strip())
        except ValueError:
            limit = 0
        if not sep or not name or limit < 1:
            raise ValueError(
                f'DLQ_HANDLER_MAX_RETRIES entry must be "Handler:limit", got {entry.strip()!r}'
            )
        limits[name] = limit
    return limits


@dataclass
class DlqSettings:
    """``DLQ_*`` environment, mapped onto :class:`DeadLetterConfig` by :meth:`get_config`."""

    BATCH_SIZE: int = field(default_factory=get_env('DLQ_BATCH_SIZE', _DEFAULT.batch_size))
    """Rows one retry step claims."""
    PAGE_SIZE: int = field(default_factory=get_env('DLQ_PAGE_SIZE', _DEFAULT.page_size))
    """Default ``list`` page size."""
    MAX_RETRIES: int = field(default_factory=get_env('DLQ_MAX_RETRIES', _DEFAULT.max_retries))
    """Default retry budget of a dead letter."""
    RETRY_BACKOFF_MULTIPLIER: float = field(
        default_factory=get_env('DLQ_RETRY_BACKOFF_MULTIPLIER', _DEFAULT.retry_backoff_multiplier)
    )
    """Retry n waits ``multiplier ** n`` seconds."""
    RETRY_MAX_INTERVAL_MS: int = field(
        default_factory=get_env('DLQ_RETRY_MAX_INTERVAL_MS', _DEFAULT.retry_max_interval_ms)
    )
    """Cap of the retry backoff (ms)."""
    CLAIM_TIMEOUT_MS: int = field(
        default_factory=get_env('DLQ_CLAIM_TIMEOUT_MS', _DEFAULT.claim_timeout_ms)
    )
    """A lease (``processing``) older than this returns to ``pending``."""
    ARCHIVE_AFTER_DAYS: int = field(
        default_factory=get_env('DLQ_ARCHIVE_AFTER_DAYS', _DEFAULT.archive_after_days)
    )
    """Terminal rows older than this move to the archive table."""
    HANDLER_MAX_RETRIES: dict[str, int] = field(
        default_factory=lambda: parse_handler_limits(get_env('DLQ_HANDLER_MAX_RETRIES', '')())
    )
    """Per-handler retry limits: ``OrderHandler:5,Other:2`` (or a JSON object)."""

    def get_config(self) -> DeadLetterConfig:
        """The validated :class:`DeadLetterConfig` (raises ``ValueError`` when invalid)."""
        return DeadLetterConfig(
            batch_size=self.BATCH_SIZE,
            page_size=self.PAGE_SIZE,
            max_retries=self.MAX_RETRIES,
            retry_backoff_multiplier=float(self.RETRY_BACKOFF_MULTIPLIER),
            retry_max_interval_ms=self.RETRY_MAX_INTERVAL_MS,
            claim_timeout_ms=self.CLAIM_TIMEOUT_MS,
            archive_after_days=self.ARCHIVE_AFTER_DAYS,
            handler_max_retries=dict(self.HANDLER_MAX_RETRIES),
        )


def get_dlq_config(settings: DlqSettings | None = None) -> DeadLetterConfig:
    """The :class:`DeadLetterConfig` of ``settings`` (default: read the environment now)."""
    return (settings or DlqSettings()).get_config()


build_dlq_config = get_dlq_config
"""Alias of :func:`get_dlq_config`."""

__all__ = ['DlqSettings', 'build_dlq_config', 'get_dlq_config', 'parse_handler_limits']
