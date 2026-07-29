"""
Redis-backed circuit-breaker storage.

Implements :class:`foundation.resiliant.circuit_breaker.ICircuitBreakerRepository`
so breaker state is shared *fleet-wide*: when one worker trips a breaker OPEN,
every other worker sees it OPEN and fails fast too (instead of each process
re-learning the dependency is down). Snapshots are stored as msgspec-JSON with a
TTL slightly longer than the recovery window, so a permanently-idle breaker
eventually evaporates from Redis.
"""

from __future__ import annotations

import msgspec
from foundation.resiliant.circuit_breaker import (
    CircuitBreakerSnapshot,
    ICircuitBreakerRepository,
)

from .redis_store import RedisStore


class RedisCircuitBreakerRepository(ICircuitBreakerRepository):
    """Shared circuit-breaker snapshots backed by a :class:`RedisStore`."""

    def __init__(
        self,
        store: RedisStore,
        *,
        key_prefix: str = 'cb',
        ttl_seconds: int = 3600,
    ) -> None:
        # A dedicated namespace keeps breaker keys away from cache entries.
        self._store = store.with_namespace(key_prefix)
        self._ttl_seconds = ttl_seconds

    def _key(self, name: str) -> str:
        return f'snapshot:{name}'

    async def get(self, name: str) -> CircuitBreakerSnapshot | None:
        raw = await self._store.get(self._key(name))
        if raw is None:
            return None
        try:
            return msgspec.json.decode(raw, type=CircuitBreakerSnapshot)
        except msgspec.DecodeError:
            # Corrupt/legacy value — treat as absent so the breaker self-heals.
            return None

    async def save(self, snapshot: CircuitBreakerSnapshot) -> None:
        await self._store.set(
            self._key(snapshot.name),
            msgspec.json.encode(snapshot),
            expires_in=self._ttl_seconds,
        )


__all__ = ['RedisCircuitBreakerRepository']
