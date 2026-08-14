#!/usr/bin/env python3
"""
🔌 Kafka connectivity smoke test (remote SASL_SSL cluster).

Reads the same ``.env`` the apps read, then:
  1. connects an admin client and lists the cluster topics,
  2. produces one message to a throwaway topic,
  3. consumes it back with a fresh consumer group.

Nothing is created or deleted on the broker unless ``--create-topic`` is
passed, so it is safe to run against production with a read/write-only user.

Usage::

    uv run python libs/messaging_kafka/tests/bin/test_kafka_connection.py
    uv run python libs/messaging_kafka/tests/bin/test_kafka_connection.py --topic ews.demo.ping
    uv run python libs/messaging_kafka/tests/bin/test_kafka_connection.py --create-topic
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from foundation.messaging.config.messaging_config import MessagingConfig
from foundation.messaging.config.messaging_settings import (
    KafkaSettings,
    build_messaging_config,
)


def load_config() -> MessagingConfig:
    """Load .env (same lookup the apps use) and build the messaging config."""
    from foundation.config.settings import get_settings

    get_settings(env_file='.env')
    return build_messaging_config(KafkaSettings())


async def main(topic: str, create_topic: bool, timeout: float) -> int:
    cfg = load_config()
    # Same security kwargs the services hand to their aiokafka clients.
    kw = cfg.build_kafka_client_kwargs()

    print('=' * 78)
    print('🔌 Kafka connectivity test')
    print('=' * 78)
    print(f'  bootstrap : {cfg.kafka_bootstrap_servers_list}')
    print(f'  protocol  : {cfg.kafka_security_protocol or "PLAINTEXT"}')
    print(f'  mechanism : {cfg.kafka_sasl_mechanism or "-"}')
    print(f'  username  : {cfg.kafka_sasl_username or "-"}')
    print(f'  trust     : {cfg.kafka_ssl_trust_source}')
    print(
        f'  tls checks: hostname={cfg.kafka_ssl_check_hostname}, '
        f'strict={cfg.kafka_ssl_strict_verify}'
    )
    print(f'  topic     : {topic}')
    print('-' * 78)

    # ---------------------------------------------------------------- admin
    admin = AIOKafkaAdminClient(
        bootstrap_servers=cfg.kafka_bootstrap_servers_list, **kw
    )
    await admin.start()
    try:
        topics = sorted(await admin.list_topics())
        print(f'✅ connected — {len(topics)} topic(s) visible')
        for name in topics:
            print(f'   • {name}')
        if create_topic and topic not in topics:
            await admin.create_topics(
                [NewTopic(name=topic, num_partitions=1, replication_factor=1)]
            )
            print(f'✅ created topic {topic}')
    finally:
        await admin.close()

    # ------------------------------------------------------------- produce
    payload = f'kafka-smoke-test {time.time()}'.encode()
    producer = AIOKafkaProducer(
        bootstrap_servers=cfg.kafka_bootstrap_servers_list, **kw
    )
    await producer.start()
    try:
        meta = await producer.send_and_wait(topic, payload)
        print(
            f'✅ produced → {meta.topic}[{meta.partition}]@{meta.offset}'
        )
    finally:
        await producer.stop()

    # ------------------------------------------------------------- consume
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=cfg.kafka_bootstrap_servers_list,
        group_id=f'kafka-smoke-test-{int(time.time())}',
        auto_offset_reset='earliest',
        enable_auto_commit=False,
        **kw,
    )
    await consumer.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
            for records in batch.values():
                for record in records:
                    if record.value == payload:
                        print(
                            f'✅ consumed back from '
                            f'{record.topic}[{record.partition}]@{record.offset}'
                        )
                        print('🎉 Kafka round-trip OK')
                        return 0
        print(f'❌ message not received within {timeout:.0f}s')
        return 1
    finally:
        await consumer.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--topic',
        default='ews.demo.ping',
        help='topic used for the round-trip (default: ews.demo.ping)',
    )
    parser.add_argument(
        '--create-topic',
        action='store_true',
        help='create the topic when missing (needs Create ACL)',
    )
    parser.add_argument(
        '--timeout', type=float, default=20.0, help='consume timeout in seconds'
    )
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(main(args.topic, args.create_topic, args.timeout)))
    except Exception as exc:  # noqa: BLE001 — surface the broker error verbatim
        print(f'❌ {type(exc).__name__}: {exc}')
        sys.exit(2)
