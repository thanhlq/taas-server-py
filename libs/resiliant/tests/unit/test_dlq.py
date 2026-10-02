"""The dead-letter queue on Postgres (mirrors ``@taas/resiliant`` ``tests/e2e/dlq.test.ts``):
atomic save, operator actions (compare-and-set), replay, the retry worker (backoff,
abandon, no double claim, stale leases) and archiving.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import msgspec
import pytest
from foundation.resiliant.dlq import DeadLetterConfig, DeadLetterError, DLQStatus, NewDeadLetter
from resiliant import ResiliantServiceBuilder
from resiliant.dlq import DLQHandlerRegistry, DLQRetryProcessor, DLQService
from resiliant.models import DLQEventTable
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Retries due at once (interval capped at 0).
CONFIG = DeadLetterConfig(
    max_retries=3, retry_max_interval_ms=0, handler_max_retries={'PayoutHandler': 5}
)


@pytest.fixture
def dlq() -> DLQService:
    return ResiliantServiceBuilder.build_dlq_service(CONFIG)


@pytest.fixture
def session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, expire_on_commit=False)


def failed(event_id: str, **overrides) -> NewDeadLetter:
    fields = {
        'event_id': event_id,
        'event_type': 'DEPOSIT_CONFIRMED',
        'handler_name': 'DepositHandler',
        'payload': {'event_id': event_id, 'amount': '100'},
        'error': 'ledger unavailable',
        'source_destination': 'idx.transfers',
        **overrides,
    }
    return NewDeadLetter(**fields)


class _Replayer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.seen: list[str] = []

    async def replay(self, record) -> None:
        if self.fail:
            raise RuntimeError('still down')
        self.seen.append(record.event_id)


# --------------------------------------------------------------------------- #
# Saving and operating
# --------------------------------------------------------------------------- #


async def test_saves_inside_the_caller_transaction_with_the_right_budget(
    db_session: AsyncSession, session_factory, dlq: DLQService
) -> None:
    async with session_factory() as other:
        await dlq.save(other, failed('lost'))
        await other.rollback()  # the consumer crashed before commit

    a = await dlq.save(db_session, failed('d1'))
    b = await dlq.save(db_session, failed('d2', handler_name='PayoutHandler'))
    assert isinstance(a.id, int)
    assert (a.status, a.max_retries, a.original_error) == (DLQStatus.PENDING, 3, 'ledger unavailable')
    assert a.failed_at is not None and a.created_at is not None
    assert b.max_retries == 5
    assert (await dlq.save(db_session, failed('d3', max_retries=7))).max_retries == 7
    assert [r.event_id for r in await dlq.list(db_session)] == ['d3', 'd2', 'd1']
    with pytest.raises(DeadLetterError):
        await dlq.save(db_session, failed('x', handler_name=''))


async def test_lists_with_filters_and_keyset_pagination(
    db_session: AsyncSession, dlq: DLQService
) -> None:
    for i in range(1, 6):
        overrides = {} if i % 2 else {'handler_name': 'PayoutHandler', 'event_type': 'PAYOUT'}
        await dlq.save(db_session, failed(f'p{i}', **overrides))
    assert len(await dlq.list(db_session, handler_name='PayoutHandler')) == 2
    assert len(await dlq.list(db_session, event_type='PAYOUT')) == 2
    assert len(await dlq.list_pending(db_session)) == 5
    page1 = await dlq.list(db_session, limit=2)
    page2 = await dlq.list(db_session, limit=2, before_id=page1[1].id)
    assert [r.event_id for r in page1 + page2] == ['p5', 'p4', 'p3', 'p2']


async def test_operator_actions_are_compare_and_set(db_session: AsyncSession, dlq: DLQService) -> None:
    record = await dlq.save(db_session, failed('op'))
    assert await dlq.cancel(db_session, record.id) is True
    assert await dlq.approve(db_session, record.id) is False
    assert await dlq.abandon(db_session, record.id) is False
    assert (await dlq.get(db_session, record.id)).status == DLQStatus.CANCELLED

    other = await dlq.save(db_session, failed('op2'))
    assert await dlq.abandon(db_session, other.id) is True
    assert await dlq.approve(db_session, other.id) is True
    assert (await dlq.get(db_session, other.id)).status == DLQStatus.APPROVED
    assert await dlq.cancel(db_session, other.id) is True
    assert await dlq.get(db_session, 999_999) is None


async def test_an_illegal_transition_raises_before_any_sql(
    db_session: AsyncSession, dlq: DLQService
) -> None:
    record = await dlq.save(db_session, failed('illegal'))
    with pytest.raises(DeadLetterError, match='illegal dead-letter transition'):
        await dlq.repository.transition(db_session, record.id, [DLQStatus.RESOLVED], DLQStatus.PENDING)
    assert (await dlq.get(db_session, record.id)).status == DLQStatus.PENDING


async def test_the_database_rejects_unknown_statuses(db_session: AsyncSession) -> None:
    with pytest.raises(Exception, match='resiliant_dlq_events_status_chk'):
        await db_session.execute(
            text(
                "insert into resiliant_dlq_events (event_id, event_type, handler_name, payload,"
                " status, original_error, failed_at) values ('e', 't', 'h', '{}', 'failed', 'x', now())"
            )
        )


async def test_save_event_takes_a_domain_event(db_session: AsyncSession, dlq: DLQService) -> None:
    class _Event(msgspec.Struct, kw_only=True):
        event_type: str = 'UserRegistered'
        event_id: str = 'evt-9'
        timestamp: datetime = datetime(2026, 1, 2, tzinfo=UTC)
        user_id: str | None = 'u-1'
        source: str | None = 'iam'
        correlation_id: str | None = 'c-1'
        payload: bytes = b'\x01'

    record = await dlq.save_event(
        db_session,
        event=_Event(),
        error='boom',
        handler_name='UserHandler',
        source_destination='iam->ews',
        traceparent='00-abc-def-01',
    )
    assert (record.event_id, record.event_type, record.handler_name) == ('evt-9', 'UserRegistered', 'UserHandler')
    assert (record.user_id, record.correlation_id, record.source_service) == ('u-1', 'c-1', 'iam')
    assert record.headers == {'traceparent': '00-abc-def-01'}
    assert record.payload['timestamp'].startswith('2026-01-02')


# --------------------------------------------------------------------------- #
# Replay and the retry worker
# --------------------------------------------------------------------------- #


async def test_replays_now_resolved_on_success(db_session: AsyncSession, dlq: DLQService) -> None:
    record = await dlq.save(db_session, failed('r1'))
    replayer = _Replayer()
    assert await dlq.replay(db_session, record.id, replayer) == DLQStatus.RESOLVED
    assert replayer.seen == ['r1']
    stored = await dlq.get(db_session, record.id)
    assert stored.processed_at is not None and stored.next_attempt_at is None
    with pytest.raises(DeadLetterError, match='not pending'):
        await dlq.replay(db_session, record.id, _Replayer())


async def test_counts_failed_retries_then_abandons_approve_gives_a_fresh_budget(
    db_session: AsyncSession, dlq: DLQService
) -> None:
    record = await dlq.save(db_session, failed('r2'))
    failing = _Replayer(fail=True)
    assert await dlq.replay(db_session, record.id, failing) == DLQStatus.PENDING
    pending = await dlq.get(db_session, record.id)
    assert pending.retry_count == 1 and pending.next_attempt_at is not None
    assert await dlq.replay(db_session, record.id, failing) == DLQStatus.PENDING
    assert await dlq.replay(db_session, record.id, failing) == DLQStatus.ABANDONED
    abandoned = await dlq.get(db_session, record.id)
    assert abandoned.retry_count == 3 and 'still down' in abandoned.last_error
    assert abandoned.next_attempt_at is None
    assert await dlq.approve(db_session, record.id) is True
    assert (await dlq.get(db_session, record.id)).retry_count == 0


async def test_failed_retries_back_off_on_the_database_clock(
    db_session: AsyncSession, session_factory
) -> None:
    service = ResiliantServiceBuilder.build_dlq_service(
        DeadLetterConfig(retry_backoff_multiplier=2.0, retry_max_interval_ms=60_000)
    )
    record = await service.save(db_session, failed('backoff'))
    await db_session.commit()
    await service.replay(db_session, record.id, _Replayer(fail=True))
    await db_session.commit()
    delay = await db_session.scalar(
        text('select extract(epoch from next_attempt_at - updated_at) from resiliant_dlq_events where id = :id'),
        {'id': record.id},
    )
    assert float(delay) == pytest.approx(2.0)  # attempt 1 -> 2 ** 1 s
    processor = DLQRetryProcessor(service=service, session_factory=session_factory, replayer=_Replayer())
    assert (await processor.process_batch()).claimed == 0  # not due yet


async def test_the_worker_routes_by_handler_name_and_never_double_claims(
    db_session: AsyncSession, session_factory, dlq: DLQService
) -> None:
    for i in range(1, 31):
        overrides = {'handler_name': 'UnknownHandler'} if i % 3 == 0 else {}
        await dlq.save(db_session, failed(f'w{i}', **overrides))
    await db_session.commit()

    replayed: list[str] = []

    async def deposit(record) -> None:
        await asyncio.sleep(0.002)
        replayed.append(record.event_id)

    registry = DLQHandlerRegistry().register('DepositHandler', deposit)
    a = ResiliantServiceBuilder.build_dlq_retry_processor(session_factory, registry, dlq)
    b = DLQRetryProcessor(service=dlq, session_factory=session_factory, replayer=registry)
    ra, rb = await asyncio.gather(a.process_batch(), b.process_batch())
    assert ra.claimed + rb.claimed == 30
    assert ra.resolved + rb.resolved == 20 and ra.failed + rb.failed == 10
    assert len(replayed) == 20 and len(set(replayed)) == 20
    stats = await dlq.stats(db_session)
    assert (stats['resolved'], stats['pending'], stats['processing']) == (20, 10, 0)
    assert stats['oldest_pending_age_ms'] is not None and stats['oldest_pending_age_ms'] >= 0
    failed_row = (await dlq.list(db_session, handler_name='UnknownHandler', limit=1))[0]
    assert 'no dead-letter handler registered' in failed_row.last_error


async def test_returns_the_lease_of_a_crashed_worker_to_pending(
    db_session: AsyncSession, session_factory, dlq: DLQService
) -> None:
    record = await dlq.save(db_session, failed('stale'))
    await db_session.commit()
    async with session_factory() as worker, worker.begin():
        claimed = await dlq.repository.claim_due(worker, 10)
    assert [r.id for r in claimed] == [record.id]
    assert (await dlq.get(db_session, record.id)).status == DLQStatus.PROCESSING
    assert await dlq.reset_stale(db_session) == 0
    await db_session.execute(
        text("update resiliant_dlq_events set updated_at = now() - interval '1 hour' where id = :id"),
        {'id': record.id},
    )
    assert await dlq.reset_stale(db_session) == 1
    assert (await dlq.get(db_session, record.id)).status == DLQStatus.PENDING


async def test_stats_list_every_status(db_session: AsyncSession, dlq: DLQService) -> None:
    stats = await dlq.stats(db_session)
    assert stats == {**{s.value: 0 for s in DLQStatus}, 'oldest_pending_age_ms': None}
    assert await dlq.get_stats(db_session) == stats


# --------------------------------------------------------------------------- #
# Archiving
# --------------------------------------------------------------------------- #


async def test_archives_old_terminal_records_in_one_statement_never_live_ones(
    db_session: AsyncSession, dlq: DLQService
) -> None:
    done = await dlq.save(db_session, failed('a1'))
    await dlq.replay(db_session, done.id, _Replayer())
    cancelled = await dlq.save(db_session, failed('a2'))
    await dlq.cancel(db_session, cancelled.id)
    live = await dlq.save(db_session, failed('a3'))
    assert await dlq.archive(db_session) == 0  # too recent
    await db_session.execute(text("update resiliant_dlq_events set updated_at = now() - interval '60 days'"))
    assert await dlq.archive(db_session) == 2
    assert [r.id for r in await dlq.list(db_session)] == [live.id]
    archived = (
        await db_session.execute(
            text('select id, event_id, status, archived_at from resiliant_dlq_events_archive order by id')
        )
    ).all()
    assert [(r.id, r.event_id, r.status) for r in archived] == [
        (done.id, 'a1', 'resolved'),
        (cancelled.id, 'a2', 'cancelled'),
    ]
    assert all(r.archived_at is not None for r in archived)


async def test_archive_moves_at_most_limit_rows(db_session: AsyncSession, dlq: DLQService) -> None:
    for i in range(3):
        record = await dlq.save(db_session, failed(f'l{i}'))
        await dlq.cancel(db_session, record.id)
    await db_session.execute(text("update resiliant_dlq_events set updated_at = now() - interval '60 days'"))
    assert await dlq.archive(db_session, older_than_days=30, limit=2) == 2
    assert await dlq.archive(db_session, limit=2) == 1
    assert await dlq.archive(db_session) == 0
    assert await db_session.scalar(text('select count(*) from resiliant_dlq_events')) == 0


async def test_builders_read_the_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('DLQ_PAGE_SIZE', '7')
    monkeypatch.setenv('DLQ_CLAIM_TIMEOUT_MS', '1234')
    service = ResiliantServiceBuilder.build_dlq_service()
    assert (service.config.page_size, service.config.claim_timeout_ms) == (7, 1234)
    assert ResiliantServiceBuilder.build_dlq_service(CONFIG).config is CONFIG
    assert DLQEventTable.__tablename__ == 'resiliant_dlq_events'
