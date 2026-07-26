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

from foundation.factory import FoundationFactory
from foundation.messaging.factory import MessagingFactory
from foundation.utils.icons import Icons
from foundation.worker.base_worker import BaseWorker
from iam.iam_factory import IamFactory
from iam_keycloak import IamServiceFactory
from messaging_faststream import initialize_messaging_service, messaging
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

    def _init_cache_service(self) -> None:
        """Register the shared Redis cache service (mirrors the API lifespan)."""
        cache_config = settings.app.get_cache_config()
        if cache_config.enabled:
            RedisCacheServiceFactory.create(cache_config)
            self.logger.info(f'{Icons.REDIS} Redis cache service initialised')
        else:
            self.logger.info(
                f'{Icons.REDIS} {Icons.OFF} Cache disabled by configuration'
            )

    async def _init_services(self) -> None:
        FoundationFactory.init_default_services()
        self._init_cache_service()
        FoundationFactory.use_resiliant(ResiliantServiceFactory())
        MessagingFactory.init_factory(
            messaging_service=await initialize_messaging_service(),
            decorator=messaging,
        )
        IamFactory.initialize_iam(IamServiceFactory())

    # ------------------------------------------------------------------ cache

    # -------------------------------------------------------------- handlers
    async def _handle_demo_event(self, event: object) -> None:
        """Demo subscriber: log every event received on :data:`DEMO_TOPIC`."""
        self.logger.info('📥 [demo] received event on %s: %r', DEMO_TOPIC, event)

    # async def _register_subscribers(self) -> None:
    #     """Register topic subscribers before the consumer loop starts.

    #     Uses the dynamic ``subscribe()`` API (independent consumer group per
    #     subscription). Domain (IAM/EWS) handlers can be registered here once
    #     migrated off the legacy ``core.*`` package.
    #     """
    #     sub_id = await self.messaging_service.subscribe(
    #         DEMO_TOPIC, self._handle_demo_event, from_beginning=True
    #     )
    #     self._subscription_ids.append(sub_id)
    #     self.logger.info(
    #         '⬅️  Subscribed to demo topic %s (sub_id=%s)', DEMO_TOPIC, sub_id
    #     )

    # ----------------------------------------------------------- task wiring
    async def initialize_worker_tasks(self) -> 'BaseWorker':
        """Wire up cache, messaging, subscribers, and background tasks.

        Overrides the base implementation to take full control of ordering:
        subscribers must be registered *before* the consumer loop starts.
        """

        await self._init_services()

        self.worker_tasks = []

        if self.config.messaging_consumer_enabled:
            consumer_task = asyncio.create_task(
                self.messaging_service.start_consuming()
            )
            self.worker_tasks.append(('messaging_consumer', consumer_task))

        return self
