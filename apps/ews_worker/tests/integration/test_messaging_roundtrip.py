"""Integration test: API-style publish is consumed by the worker's subscriber.

This exercises the *same* messaging path used at runtime:

* the API publishes via ``IMessagingService.publish`` (here: the same service), and
* the worker consumes via a dynamic ``subscribe(...)`` subscriber
  (see :meth:`ews_worker.worker.EwsWorker._register_subscribers`).

It runs against a real Kafka broker (skipped when Kafka is unreachable).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_publish_is_consumed_by_subscriber(kafka_bootstrap: str) -> None:
    # Imported after conftest configured the environment.
    from messaging_faststream import FastStreamKafkaMessagingService

    service = FastStreamKafkaMessagingService()
    topic = f"ews.demo.ping.{uuid.uuid4().hex[:8]}"
    received: list[object] = []

    async def handler(event: object) -> None:
        received.append(event)

    await service.start_producer()
    await service.subscribe(topic, handler, from_beginning=True)

    consume_task = asyncio.create_task(service.start_consuming())
    try:
        # Allow the consumer group to join before publishing.
        await asyncio.sleep(6)

        await service.publish(
            topic, {"event_type": "demo.ping", "message": "hello-from-api"}
        )

        # Wait (bounded) for the subscriber to receive the message.
        for _ in range(30):
            if received:
                break
            await asyncio.sleep(1)

        assert received, "worker subscriber did not receive the published message"
    finally:
        await service.stop()
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass
