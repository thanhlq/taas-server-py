"""Outbox relay: one poller per table, routing by target, failure handling (real database)."""

from __future__ import annotations

from typing import Any

import pytest
from foundation.resiliant.outbox import (
    IOutboxRecord,
    OutboxConfig,
    OutboxName,
    OutboxPublishError,
    OutboxStatus,
    OutboxTarget,
)
from resiliant import ResiliantServiceBuilder
from resiliant.outbox import OutboxDispatchRouter
from resiliant.outbox.factory import build_outbox_poller, build_outbox_pollers
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CONFIG = OutboxConfig(batch_size=10, max_retries=2, enable_metrics=False)


class RecordingDispatcher:
    """Messaging-target dispatcher that records deliveries (or fails on demand)."""

    target = OutboxTarget.MESSAGING

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.delivered: list[dict[str, Any]] = []

    async def dispatch(self, record: IOutboxRecord) -> None:
        if self.fail:
            raise RuntimeError('broker down')
        self.delivered.append({'channel': record.channel, 'payload': record.payload})


@pytest.fixture
def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


def test_worker_builds_one_poller_per_registered_outbox(session_factory) -> None:
    pollers = build_outbox_pollers(session_factory, dispatchers=[RecordingDispatcher()])
    assert {p.name for p in pollers} >= {OutboxName.MESSAGING, OutboxName.TRANSACTION}
    assert {p.repository.table_name for p in pollers} >= {
        'resiliant_outbox_messages',
        'resiliant_outbox_transactions',
    }
    only = build_outbox_pollers(session_factory, outboxes=['transaction'], dispatchers=[RecordingDispatcher()])
    assert [p.name for p in only] == ['transaction']


async def test_poller_delivers_transaction_records(db_session: AsyncSession, session_factory) -> None:
    service = ResiliantServiceBuilder.build_transaction_outbox_service(OutboxTarget.MESSAGING, CONFIG)
    await service.save_transaction(
        db_session, request_id='req-p1', transaction_type='deposit', payload={'a': 1}, channel='tx.in'
    )
    await db_session.commit()

    dispatcher = RecordingDispatcher()
    poller = build_outbox_poller(session_factory, OutboxName.TRANSACTION, dispatchers=[dispatcher], config=CONFIG)
    assert await poller._poll_and_publish(worker_id=0) == 1

    assert dispatcher.delivered == [{'channel': 'tx.in', 'payload': {'a': 1}}]
    stats = await service.get_stats(db_session)
    assert (stats['published'], stats['pending']) == (1, 0)


async def test_failed_delivery_is_counted_then_dead_lettered(db_session: AsyncSession, session_factory) -> None:
    service = ResiliantServiceBuilder.build_messaging_outbox_service(CONFIG)
    row = await service.save_raw_message(db_session, channel='orders', payload={}, event_type='OrderCreated')
    await db_session.commit()

    poller = build_outbox_poller(
        session_factory, OutboxName.MESSAGING, dispatchers=[RecordingDispatcher(fail=True)], config=CONFIG
    )
    await poller._poll_and_publish(worker_id=0)

    await db_session.refresh(row)
    assert row.status == OutboxStatus.FAILED
    assert row.retry_count == 1
    assert row.last_error == 'RuntimeError: broker down'
    assert row.next_attempt_at is not None  # parked until the backoff elapses


async def test_router_rejects_unknown_targets() -> None:
    router = OutboxDispatchRouter([])

    class _Record:
        id, event_type, target, channel = 'r1', 'X', OutboxTarget.MESSAGING, 'c'

    with pytest.raises(OutboxPublishError, match='No dispatcher'):
        await router.dispatch(_Record())  # type: ignore[arg-type]
