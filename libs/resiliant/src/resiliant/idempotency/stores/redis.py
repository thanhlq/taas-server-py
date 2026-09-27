"""
Redis idempotency store (``IdempotencyBackend.REDIS``).

One key per ``(handler_name, event_id)``: ``<redis_key_prefix>:<handler>:<event_id>``,
holding a small JSON record. ``SET … NX EX <ttl>`` makes the claim atomic across
workers (exactly one ``SET`` succeeds) and lets Redis expire keys itself, so
:meth:`cleanup_expired` has nothing to do.

Trade-off vs. Postgres: the key is written outside the business transaction (the
``session`` argument is ignored). If a worker crashes after committing the business
change but before the ``SET``, the event is processed again on redelivery — keep
handlers idempotent at the business level too.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from foundation import BaseService
from foundation.resiliant.idempotency import IdempotencyBackend, IdempotencyConfig, IIdempotencyStore
from foundation.utils import now_in_utc
from redis.asyncio import Redis


class RedisIdempotencyStore(IIdempotencyStore, BaseService):
    """Idempotency keys in Redis (any ``redis.asyncio`` client: single, sentinel, cluster)."""

    backend = IdempotencyBackend.REDIS

    def __init__(self, config: IdempotencyConfig, redis: Redis) -> None:
        super().__init__()
        self.config = config
        self.redis = redis

    def redis_key(self, idempotency_key: str) -> str:
        """Full Redis key of an idempotency key (namespaced by ``redis_key_prefix``)."""
        return f'{self.config.redis_key_prefix}{self.config.key_separator}{idempotency_key}'

    async def is_processed(self, session: Any, idempotency_key: str) -> bool:
        return bool(await self.redis.exists(self.redis_key(idempotency_key)))

    async def mark_processed(
        self,
        session: Any,
        idempotency_key: str,
        event_id: str,
        event_type: str,
        handler_name: str,
        *,
        saga_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        record = {
            'event_id': event_id,
            'event_type': event_type,
            'handler_name': handler_name,
            'saga_id': saga_id,
            'correlation_id': correlation_id,
            'tenant_id': tenant_id,
            'metadata': extra_metadata,
            'processed_at': now_in_utc().isoformat(),
        }
        claimed = await self.redis.set(
            self.redis_key(idempotency_key),
            json.dumps(record, default=str),
            nx=True,
            ex=self.config.ttl_seconds,
        )
        return bool(claimed)

    async def get_by_key(self, session: Any, idempotency_key: str) -> Optional[dict[str, Any]]:
        """The stored record (diagnostics / audit) — not for the hot path."""
        raw = await self.redis.get(self.redis_key(idempotency_key))
        return json.loads(raw) if raw else None

    async def cleanup_expired(
        self,
        session: Any,
        *,
        ttl_days: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> int:
        """No-op: keys carry their own TTL (``ttl_days``) and Redis expires them."""
        return 0
