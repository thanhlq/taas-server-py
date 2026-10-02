"""Outbox writers + repository on the real database (same scenarios as the
``@taas/resiliant`` outbox e2e): atomicity, dedup, lock-based claim, compare-and-set,
retry / dead letter, ordering guard, retention, stats, NOTIFY."""

from __future__ import annotations

import asyncio

import psycopg
import pytest
from foundation.resiliant.outbox import (
    OutboxConfig,
    OutboxError,
    OutboxName,
    OutboxStatus,
    OutboxTarget,
)
from resiliant.models import MessagingOutboxTable
from resiliant.outbox import OutboxFailure, OutboxRepository
from resiliant.outbox.factory import build_messaging_outbox_service
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CONFIG = OutboxConfig(batch_size=10, max_retries=2, enable_metrics=False)


@pytest.fixture
def maker(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def service():
    return build_messaging_outbox_service(CONFIG)


@pytest.fixture
def repo() -> OutboxRepository[MessagingOutboxTable]:
    return OutboxRepository(MessagingOutboxTable, CONFIG)


async def _append(service, session, n: int, **kw) -> list[MessagingOutboxTable]:
    rows = []
    for i in range(n):
        row = await service.save_raw_message(
            session,
            channel=kw.get('channel', 'orders'),
            payload={'i': i},
            event_type='OrderCreated',
            ordering_key=kw.get('ordering_key'),
        )
        rows.append(row)
    return rows


async def test_writes_join_the_callers_transaction(
    db_session: AsyncSession, maker, service
) -> None:
    await _append(service, db_session, 1)
    await db_session.rollback()  # business transaction fails -> no outbox row
    async with maker() as s:
        assert (await s.execute(select(MessagingOutboxTable))).first() is None


async def test_event_id_is_idempotent(db_session: AsyncSession, service) -> None:
    first = await service.save_raw_message(
        db_session, channel='c', payload={}, event_type='E', event_id='evt-1'
    )
    again = await service.save_raw_message(
        db_session, channel='c', payload={'x': 1}, event_type='E', event_id='evt-1'
    )
    assert (
        first is not None
        and first.status == OutboxStatus.PENDING
        and first.max_retries == 2
    )
    assert again is None


async def test_validation_before_sql(db_session: AsyncSession, service) -> None:
    with pytest.raises(OutboxError, match='payload must be a JSON object'):
        await service.enqueue(
            db_session, event_type='E', payload=[1], channel='c', event_id='x'
        )  # type: ignore[arg-type]
    with pytest.raises(OutboxError, match='channel is required'):
        await service.save_raw_message(
            db_session, channel='', payload={}, event_type='E'
        )


async def test_claim_is_lock_based_and_skips_locked_rows(
    db_session, maker, service, repo
) -> None:
    await _append(service, db_session, 3)
    await db_session.commit()
    async with maker() as a, a.begin():
        first = await repo.claim(a, 2, preserve_ordering=False)
        async with maker() as b, b.begin():
            second = await repo.claim(b, 10, preserve_ordering=False)
        assert [r.id for r in first] == sorted(r.id for r in first)
        assert {r.id for r in first}.isdisjoint({r.id for r in second})
        assert len(second) == 1
    # Nothing was marked: the claim left no trace once its transaction ended (crash safety).
    async with maker() as c:
        statuses = (
            (await c.execute(select(MessagingOutboxTable.status))).scalars().all()
        )
        assert set(statuses) == {OutboxStatus.PENDING}


async def test_claim_requires_a_transaction(db_session, repo) -> None:
    await db_session.commit()
    assert not db_session.in_transaction()
    with pytest.raises(RuntimeError, match='inside a transaction'):
        await repo.claim(db_session, 1, preserve_ordering=False)


async def test_failure_backoff_then_dead_letter(
    db_session, maker, service, repo
) -> None:
    [row] = await _append(service, db_session, 1)
    await db_session.commit()
    async with maker() as s, s.begin():
        [claimed] = await repo.claim(s, 10, preserve_ordering=False)
        status = await repo.mark_failed(
            s,
            OutboxFailure(
                record=claimed, error='boom', counted=True, retry_in_ms=60_000
            ),
        )
    assert status == OutboxStatus.FAILED
    async with maker() as s, s.begin():
        assert (
            await repo.claim(s, 10, preserve_ordering=False) == []
        )  # backoff not elapsed
        await s.execute(
            update(MessagingOutboxTable).values(
                next_attempt_at=text("now() - interval '1 second'")
            )
        )
    async with maker() as s, s.begin():
        [claimed] = await repo.claim(s, 10, preserve_ordering=False)
        assert claimed.retry_count == 1 and claimed.last_error == 'boom'
        status = await repo.mark_failed(
            s, OutboxFailure(record=claimed, error='boom', counted=True, retry_in_ms=1)
        )
    assert status == OutboxStatus.DEAD_LETTER
    async with maker() as s:
        dead = await s.get(MessagingOutboxTable, row.id)
        assert (
            dead.status == OutboxStatus.DEAD_LETTER
            and dead.next_attempt_at is None
            and dead.retry_count == 2
        )


async def test_uncounted_failure_keeps_the_budget(
    db_session, maker, service, repo
) -> None:
    await _append(service, db_session, 1)
    await db_session.commit()
    async with maker() as s, s.begin():
        [claimed] = await repo.claim(s, 10, preserve_ordering=False)
        await repo.mark_failed(
            s,
            OutboxFailure(
                record=claimed, error='target down', counted=False, retry_in_ms=1
            ),
        )
    async with maker() as s:
        row = (await s.execute(select(MessagingOutboxTable))).scalar_one()
        assert row.status == OutboxStatus.FAILED and row.retry_count == 0


async def test_status_changes_are_compare_and_set(
    db_session, maker, service, repo
) -> None:
    [row] = await _append(service, db_session, 1)
    await db_session.commit()
    async with maker() as s, s.begin():
        [claimed] = await repo.claim(s, 1, preserve_ordering=False)
        await s.execute(
            update(MessagingOutboxTable).values(status=OutboxStatus.DEAD_LETTER)
        )  # operator acted
        assert await repo.mark_published(s, [claimed.id]) == 0
    async with maker() as s:
        assert (
            await s.get(MessagingOutboxTable, row.id)
        ).status == OutboxStatus.DEAD_LETTER


async def test_ordering_guard_per_key_target_and_channel(
    db_session, maker, service, repo
) -> None:
    a1 = (await _append(service, db_session, 1, ordering_key='user-1'))[0]
    a2 = (await _append(service, db_session, 1, ordering_key='user-1'))[0]
    other_channel = (
        await _append(service, db_session, 1, ordering_key='user-1', channel='audit')
    )[0]
    other_key = (await _append(service, db_session, 1, ordering_key='user-2'))[0]
    await db_session.commit()
    async with maker() as s, s.begin():
        await s.execute(
            update(MessagingOutboxTable)
            .where(MessagingOutboxTable.id == a1.id)
            .values(
                status=OutboxStatus.FAILED,
                next_attempt_at=text("now() + interval '1 hour'"),
            )
        )
    async with maker() as s, s.begin():
        ids = {r.id for r in await repo.claim(s, 10, preserve_ordering=True)}
    assert a2.id not in ids  # waits behind the failing a1
    assert {other_channel.id, other_key.id} <= ids  # other destinations are not blocked
    async with maker() as s, s.begin():
        assert a2.id in {r.id for r in await repo.claim(s, 10, preserve_ordering=False)}


async def test_requeue_purge_and_stats(db_session, maker, service, repo) -> None:
    rows = await _append(service, db_session, 3)
    await db_session.commit()
    async with maker() as s, s.begin():
        await s.execute(
            update(MessagingOutboxTable)
            .where(MessagingOutboxTable.id == rows[0].id)
            .values(status=OutboxStatus.DEAD_LETTER)
        )
        await repo.mark_published(s, [rows[1].id])
        await s.execute(
            update(MessagingOutboxTable)
            .where(MessagingOutboxTable.id == rows[1].id)
            .values(processed_at=text("now() - interval '10 days'"))
        )
    async with maker() as s:
        stats = await repo.stats(s, exact_published=True)
        assert stats['counts'] == {
            'pending': 1,
            'published': 1,
            'failed': 0,
            'dead_letter': 1,
        }
        assert (
            stats['oldest_pending_age_ms'] is not None
            and stats['oldest_pending_age_ms'] >= 0
        )
    async with maker() as s, s.begin():
        assert await repo.requeue_dead_letters(s) == 1
        assert await repo.purge_published(s, 7 * 86_400_000) == 1
    async with maker() as s:
        assert (await repo.stats(s, exact_published=True))['counts'] == {
            'pending': 2,
            'published': 0,
            'failed': 0,
            'dead_letter': 0,
        }
        full = await service.get_stats(s)
        assert (
            full['outbox'] == OutboxName.MESSAGING
            and full['table'] == MessagingOutboxTable.__tablename__
        )


async def test_notify_on_commit_with_the_notify_strategy(db_session, db_url) -> None:
    service = build_messaging_outbox_service(
        OutboxConfig(poll_strategy='notify', notify_channel='resiliant_outbox_test')
    )
    dsn = db_url.replace('+psycopg_async', '').replace('+psycopg', '')
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as listener:
        await listener.execute('LISTEN resiliant_outbox_test')
        await service.save_raw_message(
            db_session, channel='c', payload={}, event_type='E'
        )
        await db_session.commit()
        note = await asyncio.wait_for(anext(listener.notifies()), timeout=5)
    assert note.payload == MessagingOutboxTable.__tablename__


async def test_target_is_stored_as_text(db_session, service) -> None:
    row = await service.save_raw_message(
        db_session, channel='c', payload={}, event_type='E'
    )
    await db_session.commit()
    raw = (
        await db_session.execute(
            text(f'select target, status from {MessagingOutboxTable.__tablename__}')
        )
    ).one()
    assert (
        tuple(raw) == ('messaging', 'pending') and row.target == OutboxTarget.MESSAGING
    )
