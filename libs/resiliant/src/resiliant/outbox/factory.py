from __future__ import annotations

from foundation.resiliant.outbox import OutboxConfig

from resiliant.outbox import OutboxRepository, OutboxService
from resiliant.outbox.outbox_settings import get_outbox_config


def build_outbox_repository(config: OutboxConfig | None = None) -> OutboxRepository:
    """Return an :class:`OutboxRepository` built from ``config``."""
    if config is None:
        config = OutboxConfig()
    return OutboxRepository(config)


def build_outbox_service(config: OutboxConfig | None = None) -> OutboxService:
    """Return an :class:`OutboxService` wired to a fresh repository."""
    if config is None:
        config = get_outbox_config()
    return OutboxService(
        config=config,
        repository=build_outbox_repository(config),
    )
