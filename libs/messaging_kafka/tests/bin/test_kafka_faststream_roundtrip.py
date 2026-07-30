#!/usr/bin/env python3
"""
🌊 App-level Kafka round-trip through the FastStream messaging service.

Unlike ``test_kafka_connection.py`` (raw aiokafka), this drives the exact stack
the API and workers use: ``.env`` → ``KafkaSettings`` → ``MessagingConfig`` →
``FastStreamKafkaMessagingService`` (SASL/TLS via ``faststream.security``),
including the msgpack envelope encoding.

Usage::

    uv run python libs/messaging_kafka/tests/bin/test_kafka_faststream_roundtrip.py
    uv run python libs/messaging_kafka/tests/bin/test_kafka_faststream_roundtrip.py --topic iam.user.registered
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid


async def main(topic: str, timeout: float) -> int:
    from foundation.config.settings import get_settings

    get_settings(env_file='.env')

    from messaging_faststream import FastStreamKafkaMessagingService

    service = FastStreamKafkaMessagingService()
    cfg = service._config  # noqa: SLF001 — diagnostics only

    print('=' * 78)
    print('🌊 FastStream Kafka round-trip')
    print('=' * 78)
    print(f'  bootstrap : {cfg.kafka_bootstrap_servers_list}')
    print(f'  protocol  : {cfg.kafka_security_protocol or "PLAINTEXT"}')
    print(f'  mechanism : {cfg.kafka_sasl_mechanism or "-"}')
    print(f'  trust     : {cfg.kafka_ssl_trust_source}')
    print(f'  encoding  : {cfg.message_encoding}')
    print(f'  topic     : {topic}')
    print('-' * 78)

    marker = f'hello-from-test-{uuid.uuid4().hex[:8]}'
    received: list[object] = []

    async def handler(event: object) -> None:
        print(f'📥 received: {event!r}')
        received.append(event)

    await service.start_producer()
    print('✅ producer connected')

    await service.subscribe(topic, handler, from_beginning=False)
    consume_task = asyncio.create_task(service.start_consuming())
    try:
        # Let the consumer group finish joining before publishing.
        await asyncio.sleep(8)

        await service.publish(
            topic, {'event_type': 'demo.ping', 'message': marker}
        )
        print(f'✅ published marker={marker}')

        for _ in range(int(timeout)):
            if received:
                print('🎉 FastStream round-trip OK')
                return 0
            await asyncio.sleep(1)

        print(f'❌ no message received within {timeout:.0f}s')
        return 1
    finally:
        await service.stop()
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic', default='ews.demo.ping')
    parser.add_argument('--timeout', type=float, default=30.0)
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(main(args.topic, args.timeout)))
    except Exception as exc:  # noqa: BLE001 — surface the broker error verbatim
        print(f'❌ {type(exc).__name__}: {exc}')
        sys.exit(2)
