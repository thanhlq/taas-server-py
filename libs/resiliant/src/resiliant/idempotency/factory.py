"""
Entry point for building the idempotency service with the configured store.

    build_idempotency_service()                                  # IDEMPOTENCY_BACKEND
    build_idempotency_service(IdempotencyConfig(backend=IdempotencyBackend.REDIS))
"""

from __future__ import annotations

from foundation.resiliant.idempotency import IdempotencyBackend, IdempotencyConfig, IIdempotencyStore
from redis.asyncio import Redis

from .idempotency_service import IdempotencyService
from .idempotency_settings import get_idempotency_config, get_idempotency_settings
from .stores import PostgresIdempotencyStore, RedisIdempotencyStore


def build_redis_client() -> Redis:
    """Async Redis client for the Redis store (``IDEMPOTENCY_REDIS_*``, else the cache Redis)."""
    from store_redis import create_redis_client

    return create_redis_client(get_idempotency_settings().get_redis_config())


def build_idempotency_store(config: IdempotencyConfig, redis: Redis | None = None) -> IIdempotencyStore:
    """The store for ``config.backend``; ``redis`` overrides the Redis client (tests)."""
    if config.backend is IdempotencyBackend.REDIS:
        return RedisIdempotencyStore(config, redis or build_redis_client())
    return PostgresIdempotencyStore(config)


def build_idempotency_service(
    config: IdempotencyConfig | None = None, redis: Redis | None = None
) -> IdempotencyService:
    """Idempotency service on the configured store (environment when ``config`` is omitted)."""
    config = config or get_idempotency_config()
    return IdempotencyService(config=config, store=build_idempotency_store(config, redis))
