#!/usr/bin/env python3
"""
🏗️  Create the application topics on the configured Kafka cluster.

Reads the broker/security settings from ``.env`` (same path as the apps) and
creates any missing topic from :data:`APP_TOPICS`. Existing topics are left
untouched — the script is idempotent and never deletes anything.

Usage::

    uv run python libs/messaging_kafka/tests/bin/create_kafka_topics.py --dry-run
    uv run python libs/messaging_kafka/tests/bin/create_kafka_topics.py
    uv run python libs/messaging_kafka/tests/bin/create_kafka_topics.py --partitions 3 --replication 3
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from aiokafka.admin import AIOKafkaAdminClient, NewTopic

# Topics the platform consumes/produces (see iam.iam_constants.IamTopics and
# the JS worker's TOPICS default in packages/foundation/src/conf/settings.ts).
APP_TOPICS = [
    'iam.user.registered',
    'iam.tenant.created',
    'iam.auth',
    'iam.authz',
    'dlq.events',
    'ews.demo.ping',
]


async def main(partitions: int, replication: int, dry_run: bool) -> int:
    from foundation.config.settings import get_settings

    get_settings(env_file='.env')

    from foundation.messaging.kafka.kafka_settings import (
        KafkaSettings,
        build_messaging_config,
    )

    cfg = build_messaging_config(KafkaSettings())

    print(f'🔌 bootstrap: {cfg.kafka_bootstrap_servers_list}')
    print(f'🔐 protocol : {cfg.kafka_security_protocol or "PLAINTEXT"}')
    print(f'🏗️  layout   : partitions={partitions}, replication={replication}')
    print('-' * 78)

    admin = AIOKafkaAdminClient(
        bootstrap_servers=cfg.kafka_bootstrap_servers_list,
        **cfg.build_kafka_client_kwargs(),
    )
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        missing = [name for name in APP_TOPICS if name not in existing]

        for name in APP_TOPICS:
            state = 'exists' if name in existing else 'MISSING'
            print(f'  {"✅" if name in existing else "➕"} {name} ({state})')

        if not missing:
            print('\n✅ nothing to do — all application topics exist')
            return 0

        if dry_run:
            print(f'\n🚫 dry run — would create: {missing}')
            return 0

        await admin.create_topics(
            [
                NewTopic(
                    name=name,
                    num_partitions=partitions,
                    replication_factor=replication,
                )
                for name in missing
            ]
        )
        print(f'\n✅ created {len(missing)} topic(s): {missing}')
        return 0
    finally:
        await admin.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partitions', type=int, default=3)
    parser.add_argument('--replication', type=int, default=3)
    parser.add_argument(
        '--dry-run', action='store_true', help='list what would be created'
    )
    args = parser.parse_args()
    try:
        sys.exit(
            asyncio.run(main(args.partitions, args.replication, args.dry_run))
        )
    except Exception as exc:  # noqa: BLE001 — surface the broker error verbatim
        print(f'❌ {type(exc).__name__}: {exc}')
        sys.exit(2)
