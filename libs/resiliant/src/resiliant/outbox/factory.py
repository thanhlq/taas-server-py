from __future__ import annotations

from typing import Callable, Optional

from foundation.messaging.types import MessagingServiceT
from foundation.resiliant.outbox import OutboxConfig
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.outbox import OutboxPoller, OutboxRepository, OutboxService
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


def build_outbox_poller(
    session_factory: Callable[[], AsyncSession],
    config: OutboxConfig | None = None,
    publisher: Optional[MessagingServiceT] = None,
) -> OutboxPoller:
    """Return an :class:`OutboxPoller` wired to a fresh repository.

    Args:
        session_factory: Factory that yields a new :class:`AsyncSession`.
        config: Outbox configuration. Loaded from the environment when omitted.
        publisher: Broker publisher. Resolved from the service locator lazily
            when omitted.
    """
    if config is None:
        config = get_outbox_config()
    return OutboxPoller(
        config=config,
        session_factory=session_factory,
        publisher=publisher,
        repository=build_outbox_repository(config),
    )
