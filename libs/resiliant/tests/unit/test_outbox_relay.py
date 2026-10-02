"""Outbox relay (processor + poller) on the real database: publish, retry, dead letter,
outage attribution (target circuit), ordering deferral, crash safety, routing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from foundation.resiliant.outbox import (
    IOutboxRecord,
    OutboxConfig,
    OutboxName,
    OutboxStatus,
    OutboxTarget,
)
from resiliant.models import MessagingOutboxTable
from resiliant.outbox import OutboxPoller, OutboxProcessor, OutboxRepository
from resiliant.outbox.factory import (
    build_messaging_outbox_service,
    build_outbox_pollers,
)
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Dispatcher:
    target = OutboxTarget.MESSAGING

    def __init__(
        self, fail_ids: set[int] | None = None, fail_all: bool = False, delay: float = 0
    ) -> None:
        self.fail_ids = fail_ids or set()
        self.fail_all = fail_all
        self.delay = delay
        self.delivered: list[int] = []

    async def dispatch(self, record: IOutboxRecord) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_all or record.id in self.fail_ids:
            raise RuntimeError('broker down')
        self.delivered.append(record.id)


@pytest.fixture
def maker(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


def processor(maker, dispatcher: Dispatcher, **cfg: Any) -> OutboxProcessor:
    config = OutboxConfig(
        **{'batch_size': 10, 'max_retries': 3, 'enable_metrics': False, **cfg}
    )
    return OutboxProcessor(
        name='messaging',
        repository=OutboxRepository(MessagingOutboxTable, config),
        session_factory=maker,
        dispatchers=[dispatcher],
        config=config,
    )


async def seed(maker, n: int, ordering_key: str | None = None) -> list[int]:
    service = build_messaging_outbox_service(OutboxConfig(max_retries=3))
    async with maker() as s, s.begin():
        rows = [
            await service.save_raw_message(
                s,
                channel='orders',
                payload={'i': i},
                event_type='E',
                ordering_key=ordering_key,
            )
            for i in range(n)
        ]
    return [r.id for r in rows]


async def statuses(maker) -> dict[int, OutboxStatus]:
    async with maker() as s:
        return dict(
            (
                await s.execute(
                    select(MessagingOutboxTable.id, MessagingOutboxTable.status)
                )
            ).all()
        )


async def test_publishes_in_id_order_in_one_transaction(db_session, maker) -> None:
    ids = await seed(maker, 3)
    d = Dispatcher()
    result = await processor(maker, d).process_batch()
    assert (result.claimed, result.published, result.failed) == (3, 3, 0)
    assert d.delivered == ids
    assert set((await statuses(maker)).values()) == {OutboxStatus.PUBLISHED}


async def test_a_poison_record_is_retried_then_dead_lettered(db_session, maker) -> None:
    [bad, good] = await seed(maker, 2)
    p = processor(maker, Dispatcher(fail_ids={bad}), breaker_failure_threshold=3)
    for _ in range(3):
        await p.process_batch()
        async with maker() as s, s.begin():
            await s.execute(update(MessagingOutboxTable).values(next_attempt_at=None))
    assert await statuses(maker) == {
        bad: OutboxStatus.DEAD_LETTER,
        good: OutboxStatus.PUBLISHED,
    }
    assert (
        p.circuit_state == 'closed'
    )  # one record failing alone never opens the circuit


async def test_an_outage_opens_the_circuit_and_never_dead_letters(
    db_session, maker
) -> None:
    await seed(maker, 5)
    p = processor(
        maker,
        Dispatcher(fail_all=True),
        breaker_failure_threshold=2,
        breaker_cooldown_ms=60_000,
    )
    result = await p.process_batch()
    # Two distinct records failing = target down: the circuit opens, the rest of the batch waits.
    assert result.circuit == 'open' and result.failed == 2 and result.deferred == 3
    rows = await _rows(maker)
    assert [r.status for r in rows] == [OutboxStatus.FAILED] * 2 + [
        OutboxStatus.PENDING
    ] * 3
    assert [r.retry_count for r in rows[:2]] == [
        1,
        1,
    ]  # failed while the circuit was still closed
    assert (await p.process_batch()).claimed == 0  # cooling down: no claim at all

    # After the cool-down: a probe of one; its failure is not counted (an outage never dead-letters).
    p.circuit._cooldown_ms = 0
    async with maker() as s, s.begin():
        await s.execute(update(MessagingOutboxTable).values(next_attempt_at=None))
    probe = await p.process_batch()
    assert probe.claimed == 1 and probe.failed == 1 and probe.circuit == 'open'
    assert (await _rows(maker))[0].retry_count == 1


async def _rows(maker) -> list[MessagingOutboxTable]:
    async with maker() as s:
        return list(
            (
                await s.execute(
                    select(MessagingOutboxTable).order_by(MessagingOutboxTable.id)
                )
            )
            .scalars()
            .all()
        )


async def test_ordering_defers_the_rest_of_a_failing_key(db_session, maker) -> None:
    [k1, k2, k3] = await seed(maker, 3, ordering_key='acc-1')
    result = await processor(maker, Dispatcher(fail_ids={k1})).process_batch()
    assert (result.published, result.failed, result.deferred) == (0, 1, 2)
    assert await statuses(maker) == {
        k1: OutboxStatus.FAILED,
        k2: OutboxStatus.PENDING,
        k3: OutboxStatus.PENDING,
    }


async def test_a_crash_mid_batch_rolls_back(db_session, maker) -> None:
    await seed(maker, 2)

    class Crash(Dispatcher):
        async def dispatch(self, record: IOutboxRecord) -> None:
            raise asyncio.CancelledError  # not an Exception: aborts the step like a lost process

    with pytest.raises(asyncio.CancelledError):
        await processor(maker, Crash()).process_batch()
    assert set((await statuses(maker)).values()) == {OutboxStatus.PENDING}


async def test_dispatch_timeout_is_a_failure(db_session, maker) -> None:
    [rid] = await seed(maker, 1)
    result = await processor(
        maker, Dispatcher(delay=0.2), dispatch_timeout_ms=50
    ).process_batch()
    assert result.failed == 1
    async with maker() as s:
        assert (await s.get(MessagingOutboxTable, rid)).last_error.startswith(
            'timeout:'
        )


async def test_poller_drains_and_wakes(db_session, maker) -> None:
    await seed(maker, 3)
    d = Dispatcher()
    config = OutboxConfig(
        batch_size=2,
        poll_strategy='fixed',
        fixed_poll_interval_ms=5000,
        enable_metrics=False,
    )
    poller = OutboxPoller(
        config=config, session_factory=maker, dispatchers=[d], name='messaging'
    )
    await poller.start()
    try:
        for _ in range(50):
            if len(d.delivered) == 3:
                break
            await asyncio.sleep(0.05)
        assert len(d.delivered) == 3  # 2 + drain + 1, without waiting for the 5 s sleep
        await seed(maker, 1)
        poller.wake()
        for _ in range(50):
            if len(d.delivered) == 4:
                break
            await asyncio.sleep(0.05)
        assert len(d.delivered) == 4 and poller.is_healthy()
    finally:
        await poller.stop()
    assert not poller.is_running()


async def test_one_poller_per_registered_outbox(maker) -> None:
    pollers = build_outbox_pollers(maker, dispatchers=[Dispatcher()])
    assert {p.name for p in pollers} == {OutboxName.MESSAGING, OutboxName.TRANSACTION}


async def test_unknown_target_fails_the_record(db_session, maker) -> None:
    service = build_messaging_outbox_service(OutboxConfig(max_retries=3))
    async with maker() as s, s.begin():
        row = await service.enqueue(
            s, event_type='E', payload={}, channel='c', target='webhook', event_id='w-1'
        )
    result = await processor(maker, Dispatcher()).process_batch()
    assert result.failed == 1
    async with maker() as s:
        stored = await s.get(MessagingOutboxTable, row.id)
        assert stored.target == 'webhook' and 'No dispatcher' in stored.last_error
    assert text
