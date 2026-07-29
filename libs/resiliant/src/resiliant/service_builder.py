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
from typing import TYPE_CHECKING, Callable

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.dlq import DeadLetterConfig
from foundation.resiliant.idempotency import IdempotencyConfig
from foundation.resiliant.outbox import OutboxConfig
from foundation.resiliant.saga import SagaConfig, SagaService
from foundation.resiliant.schedule import ScheduleConfig

from resiliant.dlq import DLQRepository, DLQService
from resiliant.idempotency import IdempotencyRepository, IdempotencyService
from resiliant.outbox import OutboxPoller, OutboxRepository, OutboxService
from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.saga import SagaRepository
from resiliant.schedule import ScheduleRepository, SchedulerPoller, ScheduleService
from resiliant.schedule.schedule_settings import get_schedule_config

if TYPE_CHECKING:
    from foundation.messaging.types import IMessagingService
    from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------- #
# Resiliant Factory
# --------------------------------------------------------------------------- #


class ResiliantServiceBuilder:
    """Create and wire resilience components (outbox and DLQ).

    All methods are static; callers pass an explicit config or rely on the
    library defaults. Repositories are stateless beyond their config, so a new
    instance per call is cheap and avoids shared mutable state.
    """

    _logger: Logger | None = None

    @staticmethod
    def logger() -> Logger:
        if ResiliantServiceBuilder._logger is None:
            ResiliantServiceBuilder._logger = LogFactory().get_logger('ResiliantServiceBuilder')
        return ResiliantServiceBuilder._logger

    # ----------------------------------------------------------------- outbox
    @staticmethod
    def build_outbox_repository(config: OutboxConfig | None = None) -> OutboxRepository:
        """Return an :class:`OutboxRepository` built from ``config``."""
        if config is None:
            ResiliantServiceBuilder.logger().debug('No OutboxConfig provided; using defaults.')
            config = OutboxConfig()
        return OutboxRepository(config)

    @staticmethod
    def build_outbox_service(config: OutboxConfig | None = None) -> OutboxService:
        """Return an :class:`OutboxService` wired to a fresh repository."""
        if config is None:
            ResiliantServiceBuilder.logger().debug('No OutboxConfig provided; using defaults.')
            config = get_outbox_config()
        return OutboxService(
            config=config,
            repository=ResiliantServiceBuilder.build_outbox_repository(config),
        )

    @staticmethod
    def build_outbox_poller(
        session_factory: 'Callable[[], AsyncSession]',
        config: OutboxConfig | None = None,
        publisher: 'IMessagingService | None' = None,
    ) -> 'OutboxPoller':
        """Return an :class:`OutboxPoller` wired to a fresh repository.

        The poller is a pure poller: it owns the polling / publishing loop
        only. A separate worker application drives it via ``run()`` / ``stop()``.
        """
        if config is None:
            ResiliantServiceBuilder.logger().debug(
                'No OutboxConfig provided; using defaults.'
            )
            config = get_outbox_config()
        return OutboxPoller(
            config=config,
            session_factory=session_factory,
            publisher=publisher,
            repository=ResiliantServiceBuilder.build_outbox_repository(config),
        )

    # -------------------------------------------------------------------- dlq
    @staticmethod
    def build_dlq_repository(config: DeadLetterConfig | None = None) -> DLQRepository:
        """Return a :class:`DLQRepository` built from ``config``."""
        if config is None:
            ResiliantServiceBuilder.logger().debug(
                'No DeadLetterConfig provided; using defaults.'
            )
            config = DeadLetterConfig()
        return DLQRepository(config)

    @staticmethod
    def build_dlq_service(config: DeadLetterConfig | None = None) -> DLQService:
        """Return a :class:`DLQService` wired to a fresh repository."""
        if config is None:
            config = DeadLetterConfig()
        return DLQService(
            config=config,
            repository=ResiliantServiceBuilder.build_dlq_repository(config),
        )

    # ------------------------------------------------------------ idempotency
    @staticmethod
    def build_idempotency_repository(
        config: IdempotencyConfig | None = None,
    ) -> IdempotencyRepository:
        """Return an :class:`IdempotencyRepository` built from ``config``."""
        if config is None:
            ResiliantServiceBuilder.logger().debug(
                'No IdempotencyConfig provided; using defaults.'
            )
            config = IdempotencyConfig()
        return IdempotencyRepository(config)

    @staticmethod
    def build_idempotency_service(
        config: IdempotencyConfig | None = None,
    ) -> IdempotencyService:
        """Return an :class:`IdempotencyService` wired to a fresh repository."""
        if config is None:
            ResiliantServiceBuilder.logger().debug(
                'No IdempotencyConfig provided; using defaults.'
            )
            config = IdempotencyConfig()
        return IdempotencyService(
            config=config,
            repository=ResiliantServiceBuilder.build_idempotency_repository(config),
        )

    # ------------------------------------------------------------------- saga
    @staticmethod
    def build_saga_repository(
        session_factory: 'Callable[[], AsyncSession] | None' = None,
    ) -> SagaRepository:
        """Return a :class:`SagaRepository`.

        ``session_factory`` is optional: when omitted the repository resolves
        the main database lazily on first use (mirrors the outbox poller's lazy
        publisher).
        """
        return SagaRepository(session_factory=session_factory)

    @staticmethod
    def build_saga_service(
        config: SagaConfig | None = None,
        session_factory: 'Callable[[], AsyncSession] | None' = None,
    ) -> SagaService:
        """Return a durable :class:`SagaService` backed by Postgres."""
        return SagaService(
            repository=ResiliantServiceBuilder.build_saga_repository(session_factory),
            config=config,
        )

    # --------------------------------------------------------------- schedule
    @staticmethod
    def build_schedule_repository(
        config: ScheduleConfig | None = None,
    ) -> ScheduleRepository:
        """Return a :class:`ScheduleRepository` built from ``config``."""
        return ScheduleRepository(config or get_schedule_config())

    @staticmethod
    def build_schedule_service(
        config: ScheduleConfig | None = None,
    ) -> ScheduleService:
        """Return a :class:`ScheduleService` wired to a fresh repository."""
        config = config or get_schedule_config()
        return ScheduleService(
            config=config,
            repository=ResiliantServiceBuilder.build_schedule_repository(config),
        )

    @staticmethod
    def build_scheduler_poller(
        session_factory: 'Callable[[], AsyncSession]',
        config: ScheduleConfig | None = None,
        publisher: 'IMessagingService | None' = None,
    ) -> SchedulerPoller:
        """Return a :class:`SchedulerPoller` (a pure poller driven by a worker)."""
        config = config or get_schedule_config()
        return SchedulerPoller(
            config=config,
            session_factory=session_factory,
            publisher=publisher,
            repository=ResiliantServiceBuilder.build_schedule_repository(config),
        )
