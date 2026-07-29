"""
📤 Outbox Worker

Concrete worker application built on :class:`foundation.worker.BaseWorker`.

Responsibilities:
  * initialise the FastStream Kafka messaging service (as a *publisher* only),
  * construct the :class:`resiliant.outbox.OutboxPoller`, and
  * run the poller loop until the process is stopped.

Unlike ``ews_worker`` this worker does **not** consume Kafka topics — it only
relays pending transactional-outbox events to the broker via the pure
``OutboxPoller``.

Start command::

    uv run --package outbox_worker python -m outbox_worker   # or ./start_outbox.sh
"""

from __future__ import annotations

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
from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.schedule import SchedulerPoller
from resiliant.schedule.schedule_settings import get_schedule_config


class OutboxWorker(BaseWorker):
    """Outbox relay worker.

    Runs two pure pollers side by side (no Kafka consumer):
      * :class:`OutboxPoller` — relays transactional-outbox events to the broker;
      * :class:`SchedulerPoller` — fires due durable timers / schedules.

    Both reuse the same ``FOR UPDATE SKIP LOCKED`` claiming discipline and the
    messaging service as publisher, so co-hosting them adds no new deployable.
    """

    def __init__(self) -> None:
        super().__init__(name='outbox_worker')
        self._poller: OutboxPoller | None = None
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

    # ----------------------------------------------------------- task wiring
    async def initialize_worker_tasks(self) -> 'BaseWorker':
        """Wire up messaging (publisher), resilient services, and the poller."""
        # 1. Internal services (resiliant + foundation defaults).
        await self._init_services()


        # 3. Build the pollers. Both reuse the resiliant repositories and
        #    publish through the messaging service.
        db: AdvancedDBManager = MainDatabase.get_instance()
        self._poller = OutboxPoller(
            config=get_outbox_config(),
            session_factory=db.new_session,
            publisher=self.messaging_service,
        )

        # 4. Run the poller loops as worker tasks.
        self.worker_tasks = []
        poller_task = asyncio.create_task(self._poller.run())
        self.worker_tasks.append(('outbox_poller', poller_task))
        self.logger.info(f'{Icons.OUTBOX_SERVICE} Outbox poller task started')

        schedule_config = get_schedule_config()
        if schedule_config.enabled:
            self._scheduler = SchedulerPoller(
                config=schedule_config,
                session_factory=db.new_session,
                publisher=self.messaging_service,
            )
            scheduler_task = asyncio.create_task(self._scheduler.run())
            self.worker_tasks.append(('scheduler_poller', scheduler_task))
            self.logger.info('⏰ Scheduler poller task started')

        return self

    async def shutdown(self) -> None:
        """Stop the pollers gracefully, then defer to the base shutdown."""
        if self._poller is not None:
            try:
                await self._poller.stop()
            except Exception:
                self.logger.exception('Error while stopping outbox poller')
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
            except Exception:
                self.logger.exception('Error while stopping scheduler poller')
        await super().shutdown()
