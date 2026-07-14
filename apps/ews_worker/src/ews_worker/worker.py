"""
🏃 EWS Worker

Concrete worker application built on :class:`foundation.worker.BaseWorker`
(the worker-side counterpart to ``ews_api``'s ``BaseApiApplication``).

Responsibilities:
  * initialise the Redis cache service (same as the API lifespan),
  * initialise the FastStream Kafka messaging service and register subscribers,
  * run the Kafka consumer loop, and
  * optionally relay pending transactional-outbox events to the broker.

Start command::

    uv run python -m ews_worker            # or ./start_ews_worker.sh
"""

from __future__ import annotations

import asyncio
import os

from foundation.db.advanced_db_manager import AdvancedDBManager
from foundation.factory import FoundationFactory
from foundation.worker.base_worker import BaseWorker
from messaging_faststream import initialize_messaging_service
from resiliant import ResiliantServiceFactory
from store_redis import RedisCacheServiceFactory

from .bootstrap import settings

# Demo topic the worker subscribes to. A publisher (e.g. the API, or the
# integration test) sending to this topic exercises the full messaging path.
DEMO_TOPIC = 'ews.demo.ping'


class EwsWorker(BaseWorker):
    """EWS background worker (Kafka consumer + outbox relay)."""

    def __init__(self) -> None:
        super().__init__(name='ews_worker')
        self._subscription_ids: list[str] = []
        # The base class derives the health port from a settings attribute that
        # isn't defined in this repo's Settings; read it from the environment
        # instead. Default 7100 avoids macOS AirPlay's use of port 7000.
        self.health_check_server_port = int(os.getenv('WORKER_LISTEN_PORT', '7100'))
        FoundationFactory.use_resiliant(ResiliantServiceFactory())

    # ------------------------------------------------------------------ cache
    def _init_cache(self) -> None:
        """Register the shared Redis cache service (mirrors the API lifespan)."""
        cache_config = settings.app.get_cache_config()
        if cache_config.enabled:
            RedisCacheServiceFactory.create(cache_config)
            self.logger.info('🧠 Redis cache service initialised')
        else:
            self.logger.info('🧠 ⚫ Cache disabled by configuration')

    # -------------------------------------------------------------- handlers
    async def _handle_demo_event(self, event: object) -> None:
        """Demo subscriber: log every event received on :data:`DEMO_TOPIC`."""
        self.logger.info('📥 [demo] received event on %s: %r', DEMO_TOPIC, event)

    async def _register_subscribers(self) -> None:
        """Register topic subscribers before the consumer loop starts.

        Uses the dynamic ``subscribe()`` API (independent consumer group per
        subscription). Domain (IAM/EWS) handlers can be registered here once
        migrated off the legacy ``core.*`` package.
        """
        assert self.messaging_service is not None
        sub_id = await self.messaging_service.subscribe(
            DEMO_TOPIC, self._handle_demo_event, from_beginning=True
        )
        self._subscription_ids.append(sub_id)
        self.logger.info(
            '⬅️  Subscribed to demo topic %s (sub_id=%s)', DEMO_TOPIC, sub_id
        )

    # ----------------------------------------------------------- task wiring
    async def initialize_worker_tasks(self) -> 'BaseWorker':
        """Wire up cache, messaging, subscribers, and background tasks.

        Overrides the base implementation to take full control of ordering:
        subscribers must be registered *before* the consumer loop starts.
        """
        # 1. Cache (same as the API lifespan).
        self._init_cache()

        # 2. Messaging service — also registers ``IMessagingService`` in the
        #    service locator so publishers elsewhere can resolve it.
        self.messaging_service = await initialize_messaging_service()

        # 3. Register subscribers before consumption begins.
        await self._register_subscribers()

        # 4. Kafka consumer loop (blocks until the service is stopped).
        self.worker_tasks = []
        consumer_task = asyncio.create_task(self.messaging_service.start_consuming())
        self.worker_tasks.append(('kafka_consumer', consumer_task))

        # 5. Outbox relay (optional — enable via OUTBOX_POLLER_ENABLE).
        if self.outbox_poller_enabled:
            relay_task = asyncio.create_task(self._outbox_relay_loop())
            self.worker_tasks.append(('outbox_relay', relay_task))
            self.logger.info('📤 Outbox relay enabled')
        else:
            self.logger.info('📤 ⚫ Outbox relay disabled by configuration')

        return self

    # ----------------------------------------------------------- outbox relay
    async def _outbox_relay_loop(self) -> None:
        """Periodically publish pending outbox events to the broker.

        A lightweight relay built on the ``resiliant`` transactional outbox:
        claim a batch of PENDING rows, publish each to its channel, then mark
        it PUBLISHED. Runs until the task is cancelled during shutdown.
        """
        from foundation.db.advanced_db_manager import MainDatabase
        from resiliant import ResiliantServiceBuilder

        outbox = ResiliantServiceBuilder.build_outbox_service()
        repo = outbox.repository
        db: AdvancedDBManager = MainDatabase.get_instance()
        interval_seconds = 3.0

        while True:
            try:
                async with db.new_session() as session:
                    pending = await repo.fetch_pending_batch(session, batch_size=50)
                    for event in pending:
                        assert self.messaging_service is not None
                        await self.messaging_service.publish(
                            event.channel,
                            event.payload,
                            headers=event.headers or {},
                        )
                        await repo.mark_published(session, event.id)
                    if pending:
                        self.logger.info('📤 relayed %d outbox event(s)', len(pending))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception('Outbox relay iteration failed')

            await asyncio.sleep(interval_seconds)
