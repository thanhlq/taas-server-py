#!/usr/bin/env python3
"""
📤 Publish a single test event through the app's messaging service.

Uses the production publish path (``.env`` → FastStream → SASL_SSL Kafka →
msgpack envelope), so whatever is running as a consumer (the Python worker, the
Node worker) receives it exactly as it would receive a real domain event.

Two payload shapes:

* ``--kind dict`` — a plain dict envelope. The Node worker dispatches it by
  ``event_type``; the Python worker decodes it to a dict (no registered
  serializer) and its handler registry rejects it. Useful for transport checks.
* ``--kind typed`` (default) — a real ``UserRegisteredEvent``, i.e. what the API
  publishes during signup, so the Python worker resolves a real handler.

Usage::

    uv run python libs/messaging_kafka/tests/bin/publish_test_event.py
    uv run python libs/messaging_kafka/tests/bin/publish_test_event.py \
        --kind dict --topic iam.tenant.created --event-type tenant.created
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid


def build_dict_event(event_type: str) -> tuple[dict, str]:
    """Plain dict envelope — dispatched by ``event_type`` on the Node side."""
    event_id = str(uuid.uuid4())
    tenant_id = f'tl_test_{event_id[:8]}'
    return {
        'event_id': event_id,
        'event_type': event_type,
        'retry_count': 0,
        'tenant_id': tenant_id,
        'payload': {
            'tenant_id': tenant_id,
            'name': 'Kafka Config Test Org',
            'region': 'US',
            'source': 'publish_test_event.py',
        },
    }, event_id


def build_typed_event() -> tuple[object, str]:
    """A real ``UserRegisteredEvent`` — same class the signup flow publishes."""
    from iam.auth.auth_events import UserDirectoryEventPayload, UserRegisteredEvent
    from iam.auth.types import DirectoryTenant, DirectoryUser

    event_id = str(uuid.uuid4())
    tenant_id = f'tl_test_{event_id[:8]}'
    user_id = str(uuid.uuid4())

    event = UserRegisteredEvent(
        event_id=event_id,
        user_id=user_id,
        email='kafka-test@eworksuite.com',
        username='kafka-test@eworksuite.com',
        realm_name='emtrack',
    )
    event.set_payload_object(
        UserDirectoryEventPayload(
            user=DirectoryUser(
                id=user_id,
                email='kafka-test@eworksuite.com',
                username='kafka-test@eworksuite.com',
                first_name='Kafka',
                last_name='Test',
                tenant_id=tenant_id,
                is_root_account=True,
            ),
            tenant=DirectoryTenant(
                id=tenant_id,
                name='Kafka Config Test Org',
                alias_id=tenant_id,
            ),
        )
    )
    return event, event_id


async def main(topic: str, event_type: str, kind: str) -> int:
    from foundation.config.settings import get_settings

    get_settings(env_file='.env')

    from messaging_faststream import FastStreamKafkaMessagingService

    service = FastStreamKafkaMessagingService()

    if kind == 'typed':
        event, event_id = build_typed_event()
        event_type = getattr(event, 'event_type', event_type)
    else:
        event, event_id = build_dict_event(event_type)

    await service.start_producer()
    print(f'✅ producer connected → {service._config.kafka_bootstrap_servers_list}')  # noqa: SLF001
    await service.publish(topic, event)
    print(
        f'✅ published kind={kind} event_id={event_id} '
        f'event_type={event_type} topic={topic}'
    )
    await service.stop()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['typed', 'dict'], default='typed')
    parser.add_argument('--topic', default='iam.user.registered')
    parser.add_argument('--event-type', default='user.registered')
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(main(args.topic, args.event_type, args.kind)))
    except Exception as exc:  # noqa: BLE001 — surface the broker error verbatim
        print(f'❌ {type(exc).__name__}: {exc}')
        sys.exit(2)
