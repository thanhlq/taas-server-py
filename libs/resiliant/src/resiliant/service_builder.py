"""Static builders for the resilience components (outbox, DLQ, idempotency, saga, schedule).

Apps normally use the cached ``ResiliantServiceFactory``; these builders create
fresh, explicitly configured instances (tests, workers):

    outbox = ResiliantServiceBuilder.build_messaging_outbox_service()
    dlq = ResiliantServiceBuilder.build_dlq_service()

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
from foundation.resiliant.idempotency import IdempotencyConfig, IIdempotencyStore
from foundation.resiliant.outbox import OutboxConfig, OutboxName, OutboxTarget
from foundation.resiliant.saga import SagaConfig
from foundation.resiliant.schedule import ScheduleConfig

from resiliant.dlq import DLQRepository, DLQService
from resiliant.idempotency import IdempotencyService, get_idempotency_config
from resiliant.idempotency import factory as idempotency_factory
from resiliant.outbox import (
    MessagingOutboxService,
    OutboxPoller,
    OutboxRepository,
    OutboxService,
    TransactionOutboxService,
)
from resiliant.outbox import factory as outbox_factory
from resiliant.saga import SagaRepository, SagaService
from resiliant.schedule import ScheduleRepository, SchedulerPoller, ScheduleService
from resiliant.schedule.schedule_settings import get_schedule_config

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from foundation.messaging.types import MessagingServiceT
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
    # Delegates to ``resiliant.outbox.factory`` (the outbox entry point).
    @staticmethod
    def build_outbox_repository(
        config: OutboxConfig | None = None, outbox: str = OutboxName.MESSAGING
    ) -> OutboxRepository:
        """Repository bound to the table of ``outbox`` (messaging by default)."""
        return outbox_factory.build_outbox_repository(outbox, config)

    @staticmethod
    def build_outbox_service(
        config: OutboxConfig | None = None,
        outbox: str = OutboxName.MESSAGING,
        target: OutboxTarget | None = None,
    ) -> OutboxService:
        """Service writing to ``outbox`` (messaging by default)."""
        return outbox_factory.build_outbox_service(outbox, target, config)

    @staticmethod
    def build_messaging_outbox_service(config: OutboxConfig | None = None) -> MessagingOutboxService:
        """The messaging outbox service (``IOutboxService``)."""
        return outbox_factory.build_messaging_outbox_service(config)

    @staticmethod
    def build_transaction_outbox_service(
        target: OutboxTarget = OutboxTarget.MESSAGING, config: OutboxConfig | None = None
    ) -> TransactionOutboxService:
        """The transaction outbox service (``ITransactionOutboxService``) for ``target``."""
        return outbox_factory.build_transaction_outbox_service(target, config)

    @staticmethod
    def build_outbox_poller(
        session_factory: 'Callable[[], AsyncSession]',
        config: OutboxConfig | None = None,
        publisher: 'MessagingServiceT | None' = None,
        outbox: str = OutboxName.MESSAGING,
    ) -> 'OutboxPoller':
        """Pure poller for one outbox table (a worker drives ``run()`` / ``stop()``)."""
        return outbox_factory.build_outbox_poller(session_factory, outbox, publisher, config=config)

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
    # Delegates to ``resiliant.idempotency.factory`` (store picked from ``config.backend``).
    @staticmethod
    def build_idempotency_store(
        config: IdempotencyConfig | None = None, redis: 'Redis | None' = None
    ) -> IIdempotencyStore:
        """The store for ``config.backend`` (``IDEMPOTENCY_*`` environment when omitted)."""
        return idempotency_factory.build_idempotency_store(config or get_idempotency_config(), redis)

    @staticmethod
    def build_idempotency_repository(config: IdempotencyConfig | None = None) -> IIdempotencyStore:
        """Deprecated alias of :meth:`build_idempotency_store`."""
        return ResiliantServiceBuilder.build_idempotency_store(config)

    @staticmethod
    def build_idempotency_service(
        config: IdempotencyConfig | None = None, redis: 'Redis | None' = None
    ) -> IdempotencyService:
        """Idempotency service on the configured store (``IDEMPOTENCY_BACKEND``)."""
        return idempotency_factory.build_idempotency_service(config, redis)

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
        publisher: 'MessagingServiceT | None' = None,
    ) -> SchedulerPoller:
        """Return a :class:`SchedulerPoller` (a pure poller driven by a worker)."""
        config = config or get_schedule_config()
        return SchedulerPoller(
            config=config,
            session_factory=session_factory,
            publisher=publisher,
            repository=ResiliantServiceBuilder.build_schedule_repository(config),
        )
