"""
📤 Outbox Worker

Concrete worker application built on :class:`foundation.worker.BaseWorker`.

Responsibilities:
  * initialise the FastStream Kafka messaging service (as a *publisher* only),
  * build one :class:`resiliant.outbox.OutboxPoller` per registered outbox
    (messaging, transaction, … — narrow with ``OUTBOX_POLL_OUTBOXES``), and
  * run the poller loops until the process is stopped.

Unlike ``ews_worker`` this worker does **not** consume Kafka topics — it only
relays pending transactional-outbox events to the broker via the pure
``OutboxPoller``.

Start command::

    uv run --package outbox_worker python -m outbox_worker   # or ./start_outbox.sh
"""

from __future__ import annotations
from iam.iam_factory import IamFactory
from iam_keycloak import IamServiceFactory

import asyncio
import os

from foundation.db.advanced_db_manager import AdvancedDBManager, MainDatabase
from foundation.factory import FoundationFactory
from foundation.messaging.factory import MessagingFactory
from foundation.utils.icons import Icons
from foundation.worker.base_worker import BaseWorker
from messaging_faststream import initialize_messaging_service, messaging
from resiliant import ResiliantServiceFactory
from resiliant.outbox import OutboxPoller
from resiliant.outbox.factory import build_outbox_pollers
from resiliant.outbox.outbox_settings import get_polled_outboxes
from resiliant.maintenances import (
    define_maintenance_jobs,
    register_maintenance_callbacks,
)
from resiliant.schedule import SchedulerPoller
from resiliant.schedule.schedule_settings import get_schedule_config


class OutboxWorker(BaseWorker):
    """Outbox relay worker.

    Runs pure pollers side by side (no Kafka consumer):
      * :class:`OutboxPoller` (one per outbox table) — relays records to their target;
      * :class:`SchedulerPoller` — fires due durable timers / schedules.

    Both reuse the same ``FOR UPDATE SKIP LOCKED`` claiming discipline and the
    messaging service as publisher, so co-hosting them adds no new deployable.
    """

    def __init__(self) -> None:
        super().__init__(name='outbox_worker')
        self._pollers: list[OutboxPoller] = []
        self._scheduler: SchedulerPoller | None = None
        # The base class derives the health port from a settings attribute that
        # isn't defined in this repo's Settings; read it from the environment
        # instead. Default 7110 keeps it distinct from ews_worker (7100).
        self.health_check_server_port = int(os.getenv('WORKER_LISTEN_PORT', '7110'))

    async def _init_services(self) -> None:
        FoundationFactory.init_default_services()
        FoundationFactory.use_resiliant(ResiliantServiceFactory())
        MessagingFactory.init_factory(
            messaging_service=await initialize_messaging_service(),
            decorator=messaging,
        )
        IamFactory.initialize_iam(IamServiceFactory())

    # ----------------------------------------------------------- task wiring
    async def initialize_worker_tasks(self) -> 'BaseWorker':
        """Wire up messaging (publisher), resilient services, and the poller."""
        # 1. Internal services (resiliant + foundation defaults).
        await self._init_services()


        # 2. One poller per outbox table; messaging-target records are published
        #    through the messaging service.
        db: AdvancedDBManager = MainDatabase.get_instance()
        self._pollers = build_outbox_pollers(
            session_factory=db.new_session,
            publisher=self.messaging_service,
            outboxes=get_polled_outboxes(),
        )

        # 3. Run the poller loops as worker tasks.
        self.worker_tasks = []
        for poller in self._pollers:
            task = asyncio.create_task(poller.run())
            self.worker_tasks.append((f'outbox_poller:{poller.name}', task))
            self.logger.info(f'{Icons.OUTBOX_SERVICE} Outbox poller "{poller.name}" started')

        schedule_config = get_schedule_config()
        if schedule_config.enabled:
            self._scheduler = SchedulerPoller(
                config=schedule_config,
                session_factory=db.new_session,
                publisher=self.messaging_service,
            )
            # Register in-process maintenance handlers, then ensure the CRON row
            # exists (idempotent), before the poller starts firing jobs.
            register_maintenance_callbacks(self._scheduler)
            await define_maintenance_jobs()

            scheduler_task = asyncio.create_task(self._scheduler.run())
            self.worker_tasks.append(('scheduler_poller', scheduler_task))
            self.logger.info('⏰ Scheduler poller task started')

        return self

    async def shutdown(self) -> None:
        """Stop the pollers gracefully, then defer to the base shutdown."""
        for poller in self._pollers:
            try:
                await poller.stop()
            except Exception:
                self.logger.exception(f'Error while stopping outbox poller "{poller.name}"')
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
            except Exception:
                self.logger.exception('Error while stopping scheduler poller')
        await super().shutdown()
