"""Idempotency service on both stores — same protocol as ``@taas/resiliant``.

Postgres: the test database; Redis: the local ``store`` Redis of docker-compose.infra.yml,
DB 15 (``IDEMPOTENCY_TEST_REDIS_URL``, default ``redis://localhost:16380/15``); the Redis
cases skip when it is not reachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from foundation.resiliant.idempotency import (
    DuplicateEventError,
    IdempotencyBackend,
    IdempotencyConfig,
    IdempotencyInProgressError,
)
from redis.asyncio import Redis, from_url
from resiliant.idempotency import (
    IdempotencyService,
    PostgresIdempotencyStore,
    RedisIdempotencyStore,
)
from resiliant.idempotency.stores.redis import LEASE_PREFIX
from resiliant.models import ProcessedEventTable
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REDIS_URL = os.environ.get('IDEMPOTENCY_TEST_REDIS_URL', 'redis://localhost:16380/15')


@pytest.fixture
async def redis_or_none() -> AsyncGenerator[Redis | None]:
    client = from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        yield None
        return
    yield client
    await client.aclose()


@pytest.fixture
def redis(redis_or_none: Redis | None) -> Redis:
    if redis_or_none is None:
        pytest.skip(f'Redis not reachable at {REDIS_URL}')
    return redis_or_none


@pytest.fixture(params=[IdempotencyBackend.POSTGRES, IdempotencyBackend.REDIS])
def service(request, db_session, redis_or_none) -> IdempotencyService:
    config = IdempotencyConfig(
        backend=request.param,
        redis_key_prefix=f'test-{uuid.uuid4().hex[:8]}',
        log_duplicates=False,
    )
    if request.param is IdempotencyBackend.REDIS:
        if redis_or_none is None:
            pytest.skip(f'Redis not reachable at {REDIS_URL}')
        return IdempotencyService(config, RedisIdempotencyStore(config, redis_or_none))
    return IdempotencyService(config, PostgresIdempotencyStore(config))


async def test_runs_once_then_skips_duplicates(
    service: IdempotencyService, db_session: AsyncSession
) -> None:
    runs: list[str] = []
    for _ in range(2):
        async with service.guard(
            db_session, 'evt-1', 'DepositHandler', 'deposit.completed'
        ) as fresh:
            if fresh:
                runs.append('work')
    await db_session.commit()
    assert runs == ['work']
    assert await service.is_processed(
        db_session, service.build_key('evt-1', 'DepositHandler')
    )
    # Another handler of the same event is independent (fan-out).
    outcome = await service.run_once(
        db_session,
        event_id='evt-1',
        handler_name='AuditHandler',
        work=lambda s: _value(7),
    )
    assert (outcome.status, outcome.key, outcome.result) == (
        'processed',
        'AuditHandler:evt-1',
        7,
    )


async def _value(v: int) -> int:
    return v


async def test_a_failure_leaves_the_key_unrecorded(
    service: IdempotencyService, db_session: AsyncSession
) -> None:
    with pytest.raises(RuntimeError):
        async with service.guard(db_session, 'evt-2', 'H') as fresh:
            assert fresh
            raise RuntimeError('handler failed')
    assert not await service.is_processed(db_session, 'H:evt-2')
    async with service.guard(db_session, 'evt-2', 'H') as fresh:
        assert fresh  # retried safely


async def test_strict_mode_raises_on_duplicates(
    service: IdempotencyService, db_session: AsyncSession
) -> None:
    async with service.guard(db_session, 'evt-3', 'H') as fresh:
        assert fresh
    await db_session.commit()
    with pytest.raises(DuplicateEventError):
        async with service.guard(db_session, 'evt-3', 'H', raise_on_duplicate=True):
            pytest.fail('body must not run')


async def test_postgres_claims_first_and_rolls_back_with_the_work(
    db_session: AsyncSession, db_engine
) -> None:
    """The key is inserted before the work, in a savepoint of the caller's transaction."""
    config = IdempotencyConfig(log_duplicates=False)
    service = IdempotencyService(config, PostgresIdempotencyStore(config))
    async with service.guard(
        db_session, 'evt-4', 'H', tenant_id=42, metadata={'k': 'v'}
    ) as fresh:
        assert fresh
        row = (
            await db_session.execute(select(ProcessedEventTable))
        ).scalar_one()  # visible inside the work
        assert (row.idempotency_key, row.tenant_id, row.extra_metadata) == (
            'H:evt-4',
            '42',
            {'k': 'v'},
        )
    await (
        db_session.rollback()
    )  # the business transaction fails -> the claim goes with it
    maker = async_sessionmaker(bind=db_engine)
    async with maker() as other:
        assert (await other.execute(select(ProcessedEventTable))).first() is None


async def test_postgres_concurrent_duplicate_waits_then_skips(
    db_session, db_engine
) -> None:
    config = IdempotencyConfig(log_duplicates=False)
    service = IdempotencyService(config, PostgresIdempotencyStore(config))
    maker = async_sessionmaker(bind=db_engine)
    runs: list[str] = []

    async def worker(name: str, hold: float) -> None:
        async with maker() as session:
            async with service.guard(session, 'evt-5', 'H') as fresh:
                if fresh:
                    runs.append(name)
                    await asyncio.sleep(hold)
            await session.commit()

    await asyncio.gather(worker('first', 0.3), worker('second', 0))
    assert len(runs) == 1


async def test_postgres_cleanup_expired(db_session: AsyncSession) -> None:
    config = IdempotencyConfig(ttl_days=1, log_duplicates=False)
    service = IdempotencyService(config, PostgresIdempotencyStore(config))
    for i in range(3):
        await service.mark_processed(db_session, f'H:e{i}', f'e{i}', '', 'H')
    await db_session.execute(
        text(
            f"update {ProcessedEventTable.__tablename__} set created_at = now() - interval '2 days' where event_id in ('e0', 'e1')"
        )
    )
    assert await service.cleanup_expired(db_session, batch_size=1) == 1
    assert await service.cleanup_expired(db_session) == 1
    assert await service.cleanup_expired(db_session) == 0


async def test_redis_lease_protocol(redis: Redis, db_session: AsyncSession) -> None:
    config = IdempotencyConfig(
        backend=IdempotencyBackend.REDIS,
        redis_key_prefix=f'lease-{uuid.uuid4().hex[:8]}',
        lease_ms=5000,
    )
    store = RedisIdempotencyStore(config, redis)
    service = IdempotencyService(config, store)
    key = store.redis_key('H:evt-6')
    async with service.guard(db_session, 'evt-6', 'H') as fresh:
        assert fresh
        held = (await redis.get(key)).decode()
        assert held.startswith(LEASE_PREFIX) and 0 < await redis.pttl(key) <= 5000
        with pytest.raises(
            IdempotencyInProgressError
        ):  # another worker: nack, never ack
            async with service.guard(db_session, 'evt-6', 'H'):
                pass
    record = await store.get_by_key(db_session, 'H:evt-6')
    assert record['handler_name'] == 'H' and await redis.pttl(key) > 86_400_000
    # A failed work deletes only its own lease.
    with pytest.raises(RuntimeError):
        async with service.guard(db_session, 'evt-7', 'H'):
            raise RuntimeError('boom')
    assert await redis.get(store.redis_key('H:evt-7')) is None
