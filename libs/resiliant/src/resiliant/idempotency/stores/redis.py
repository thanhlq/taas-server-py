"""
Redis idempotency store — same lease protocol as ``RedisIdempotencyStore`` of
``@taas/resiliant`` (key ``<prefix>:<handler>:<event_id>``):

1. a stored record (not a lease) → duplicate, skip;
2. ``SET key lease:<token> NX PX lease_ms`` → we own the work; someone else's lease →
   :class:`IdempotencyInProgressError` (nack / retry later, never ack);
3. the work raises → delete our lease (compare-and-delete), re-raise;
4. the work succeeds → store the record with the retention TTL.

A crash between 2 and 4 leaves a lease that expires after ``lease_ms``: the event is
processed again (at-least-once), never lost. The session is ignored.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from foundation.resiliant.idempotency import (
    IdempotencyBackend,
    IdempotencyConfig,
    IdempotencyInProgressError,
    IIdempotencyStore,
)
from foundation.utils import now_in_utc
from redis.asyncio import Redis

LEASE_PREFIX = 'lease:'
COMPARE_AND_DELETE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisIdempotencyStore(IIdempotencyStore):
    backend = IdempotencyBackend.REDIS

    def __init__(self, config: IdempotencyConfig, redis: Redis) -> None:
        self.config = config
        self.redis = redis

    def redis_key(self, idempotency_key: str) -> str:
        return f'{self.config.redis_key_prefix}{self.config.key_separator}{idempotency_key}'

    @property
    def ttl_ms(self) -> int:
        return self.config.ttl_days * 86_400_000

    @staticmethod
    def record(scope: dict[str, Any]) -> str:
        return json.dumps(
            {
                'event_id': scope.get('event_id'),
                'event_type': scope.get('event_type') or '',
                'handler_name': scope.get('handler_name'),
                'saga_id': scope.get('saga_id'),
                'correlation_id': scope.get('correlation_id'),
                'tenant_id': scope.get('tenant_id'),
                'metadata': scope.get('metadata'),
                'processed_at': now_in_utc().isoformat(),
            },
            default=str,
        )

    @asynccontextmanager
    async def claim(
        self, session: Any, idempotency_key: str, scope: dict[str, Any]
    ) -> AsyncIterator[bool]:
        key = self.redis_key(idempotency_key)
        current = _text(await self.redis.get(key))
        if current is not None and not current.startswith(LEASE_PREFIX):
            yield False
            return
        lease = f'{LEASE_PREFIX}{uuid.uuid4()}'
        if not await self.redis.set(key, lease, nx=True, px=self.config.lease_ms):
            now = _text(await self.redis.get(key))
            if now is not None and not now.startswith(LEASE_PREFIX):
                yield False
                return
            raise IdempotencyInProgressError(idempotency_key)
        try:
            yield True
        except BaseException:
            try:
                await self.redis.eval(COMPARE_AND_DELETE, 1, key, lease)
            except Exception:  # noqa: BLE001 - the lease expires anyway
                pass
            raise
        await self.redis.set(key, self.record(scope), px=self.ttl_ms)

    async def is_processed(self, session: Any, idempotency_key: str) -> bool:
        value = _text(await self.redis.get(self.redis_key(idempotency_key)))
        return value is not None and not value.startswith(LEASE_PREFIX)

    async def mark_processed(
        self,
        session: Any,
        idempotency_key: str,
        event_id: str,
        event_type: str,
        handler_name: str,
        *,
        saga_id: str | None = None,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> bool:
        scope = {
            'event_id': event_id,
            'event_type': event_type,
            'handler_name': handler_name,
            'saga_id': saga_id,
            'correlation_id': correlation_id,
            'tenant_id': tenant_id,
            'metadata': extra_metadata,
        }
        return bool(
            await self.redis.set(
                self.redis_key(idempotency_key),
                self.record(scope),
                nx=True,
                px=self.ttl_ms,
            )
        )

    async def get_by_key(
        self, session: Any, idempotency_key: str
    ) -> dict[str, Any] | None:
        value = _text(await self.redis.get(self.redis_key(idempotency_key)))
        return (
            json.loads(value) if value and not value.startswith(LEASE_PREFIX) else None
        )

    async def cleanup_expired(
        self,
        session: Any,
        *,
        ttl_days: int | None = None,
        batch_size: int | None = None,
    ) -> int:
        """Keys carry their own TTL."""
        return 0


__all__ = ['LEASE_PREFIX', 'RedisIdempotencyStore']
