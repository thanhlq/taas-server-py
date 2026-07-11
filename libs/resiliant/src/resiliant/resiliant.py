"""Central factory for resilience components (outbox + DLQ).

``ResiliantFactory`` is the single entry point applications use to obtain
configured, database-backed resilience services. It hides construction details
(config defaults, repository wiring) behind a small static API:

    outbox = ResiliantFactory.get_outbox_service()
    dlq = ResiliantFactory.get_dlq_service()

    async with session.begin():
        await outbox.save_raw_message(
            session, channel="orders", payload={...}, event_type="OrderCreated"
        )
"""

from __future__ import annotations

from logging import Logger

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.dlq import DeadLetterConfig
from foundation.resiliant.outbox import OutboxConfig

from resiliant.dlq import DLQRepository, DLQService
from resiliant.outbox import OutboxRepository, OutboxService


class ResiliantFactory:
    """Create and wire resilience components (outbox and DLQ).

    All methods are static; callers pass an explicit config or rely on the
    library defaults. Repositories are stateless beyond their config, so a new
    instance per call is cheap and avoids shared mutable state.
    """

    _logger: Logger | None = None

    @staticmethod
    def logger() -> Logger:
        if ResiliantFactory._logger is None:
            ResiliantFactory._logger = LogFactory().get_logger("ResiliantFactory")
        return ResiliantFactory._logger

    # ----------------------------------------------------------------- outbox
    @staticmethod
    def get_outbox_repository(config: OutboxConfig | None = None) -> OutboxRepository:
        """Return an :class:`OutboxRepository` built from ``config``."""
        if config is None:
            ResiliantFactory.logger().debug("No OutboxConfig provided; using defaults.")
            config = OutboxConfig()
        return OutboxRepository(config)

    @staticmethod
    def get_outbox_service(config: OutboxConfig | None = None) -> OutboxService:
        """Return an :class:`OutboxService` wired to a fresh repository."""
        if config is None:
            config = OutboxConfig()
        return OutboxService(
            config=config,
            repository=ResiliantFactory.get_outbox_repository(config),
        )

    # -------------------------------------------------------------------- dlq
    @staticmethod
    def get_dlq_repository(config: DeadLetterConfig | None = None) -> DLQRepository:
        """Return a :class:`DLQRepository` built from ``config``."""
        if config is None:
            ResiliantFactory.logger().debug(
                "No DeadLetterConfig provided; using defaults."
            )
            config = DeadLetterConfig()
        return DLQRepository(config)

    @staticmethod
    def get_dlq_service(config: DeadLetterConfig | None = None) -> DLQService:
        """Return a :class:`DLQService` wired to a fresh repository."""
        if config is None:
            config = DeadLetterConfig()
        return DLQService(
            config=config,
            repository=ResiliantFactory.get_dlq_repository(config),
        )
