"""Idempotency service on both stores (Postgres: ``.env.test`` DB; Redis: local, DB 15).

The same scenarios run against each backend; Redis tests skip when no Redis is
reachable (``IDEMPOTENCY_TEST_REDIS_URL``, default ``redis://localhost:6379/15``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from foundation.resiliant.idempotency import DuplicateEventError, IdempotencyBackend, IdempotencyConfig
from redis.asyncio import Redis, from_url
from resiliant import ResiliantServiceBuilder
from resiliant.idempotency import (
    IdempotencyService,
    IdempotencySettings,
    PostgresIdempotencyStore,
    RedisIdempotencyStore,
)
from sqlalchemy.ext.asyncio import AsyncSession

REDIS_URL = os.environ.get('IDEMPOTENCY_TEST_REDIS_URL', 'redis://localhost:6379/15')


@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis | None]:
    """Local Redis client, or ``None`` when unreachable (Redis cases then skip)."""
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
def redis(redis_client: Redis | None) -> Redis:
    if redis_client is None:
        pytest.skip(f'Redis not reachable at {REDIS_URL}')
    return redis_client


@pytest.fixture(params=[IdempotencyBackend.POSTGRES, IdempotencyBackend.REDIS])
async def service(
    request, db_session: AsyncSession, redis_client: Redis | None
) -> AsyncGenerator[IdempotencyService]:
    backend = request.param
    # Unique namespace per test so parallel / repeated runs never collide.
    config = IdempotencyConfig(backend=backend, redis_key_prefix=f'test-idem-{uuid.uuid4().hex[:8]}', ttl_days=1)
    if backend is IdempotencyBackend.REDIS:
        if redis_client is None:
            pytest.skip(f'Redis not reachable at {REDIS_URL}')
        yield ResiliantServiceBuilder.build_idempotency_service(config, redis=redis_client)
        async for key in redis_client.scan_iter(f'{config.redis_key_prefix}*'):
            await redis_client.delete(key)
    else:
        yield ResiliantServiceBuilder.build_idempotency_service(config)


def test_factory_picks_the_store_from_the_backend() -> None:
    pg = ResiliantServiceBuilder.build_idempotency_service(IdempotencyConfig())
    assert isinstance(pg.store, PostgresIdempotencyStore)
    redis_cfg = IdempotencyConfig(backend=IdempotencyBackend.REDIS)
    svc = ResiliantServiceBuilder.build_idempotency_service(redis_cfg, redis=from_url(REDIS_URL))
    assert isinstance(svc.store, RedisIdempotencyStore)


def test_settings_parse_the_backend() -> None:
    assert IdempotencySettings(BACKEND='REDIS').get_config().backend is IdempotencyBackend.REDIS
    assert IdempotencySettings(BACKEND='postgres').get_config().backend is IdempotencyBackend.POSTGRES
    with pytest.raises(ValueError):
        IdempotencySettings(BACKEND='mongo').get_config()


async def test_guard_runs_once_per_handler_and_event(service: IdempotencyService, db_session) -> None:
    runs = 0
    for _ in range(2):
        async with service.guard(db_session, 'evt-1', 'OrderHandler', 'OrderCreated') as fresh:
            if fresh:
                runs += 1
        await db_session.commit()
    assert runs == 1
    assert await service.is_processed(db_session, service.build_key('evt-1', 'OrderHandler'))
    # Another handler of the same event is independent (fan-out).
    async with service.guard(db_session, 'evt-1', 'AuditHandler') as fresh:
        assert fresh
    await db_session.commit()


async def test_strict_duplicate_raises(service: IdempotencyService, db_session) -> None:
    async with service.guard(db_session, 'evt-2', 'H'):
        pass
    await db_session.commit()
    with pytest.raises(DuplicateEventError) as err:
        async with service.guard(db_session, 'evt-2', 'H', raise_on_duplicate=True):
            pytest.fail('body must not run on a duplicate')
    assert err.value.idempotency_key == service.build_key('evt-2', 'H')


async def test_failed_body_is_not_recorded(service: IdempotencyService, db_session) -> None:
    with pytest.raises(RuntimeError):
        async with service.guard(db_session, 'evt-3', 'H'):
            raise RuntimeError('handler failed')
    await db_session.rollback()
    assert not await service.is_processed(db_session, service.build_key('evt-3', 'H'))


async def test_mark_processed_is_claim_once(service: IdempotencyService, db_session) -> None:
    key = service.build_key('evt-4', 'H')
    assert await service.mark_processed(db_session, key, 'evt-4', 'T', 'H') is True
    await db_session.commit()
    assert await service.mark_processed(db_session, key, 'evt-4', 'T', 'H') is False


async def test_redis_keys_expire_by_themselves(redis: Redis) -> None:
    config = IdempotencyConfig(
        backend=IdempotencyBackend.REDIS, redis_key_prefix=f'test-idem-{uuid.uuid4().hex[:8]}', ttl_days=2
    )
    store = RedisIdempotencyStore(config, redis)
    assert await store.mark_processed(None, 'H:evt-5', 'evt-5', 'T', 'H', correlation_id='c-1') is True
    ttl = await redis.ttl(store.redis_key('H:evt-5'))
    assert 2 * 86_400 - 5 <= ttl <= 2 * 86_400
    record = await store.get_by_key(None, 'H:evt-5')
    assert record is not None and record['correlation_id'] == 'c-1'
    assert await store.cleanup_expired(None) == 0
    await redis.delete(store.redis_key('H:evt-5'))
