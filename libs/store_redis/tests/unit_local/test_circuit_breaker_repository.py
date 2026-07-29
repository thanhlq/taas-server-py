"""Tests for `RedisCircuitBreakerRepository` using an in-memory fake store.

Verifies the serialization / key-namespacing contract without a live Redis
(the repository only relies on the ``RedisStore`` get/set/with_namespace API).
"""

from __future__ import annotations

from typing import Any

from foundation.resiliant.circuit_breaker import CircuitBreakerSnapshot, CircuitState
from store_redis.circuit_breaker_repository import RedisCircuitBreakerRepository


class FakeRedisStore:
    """Minimal stand-in for ``RedisStore`` (namespacing + get/set)."""

    def __init__(
        self,
        namespace: str = 'TAAS',
        data: dict[str, bytes] | None = None,
        set_calls: list[tuple[str, Any]] | None = None,
    ):
        self.namespace = namespace
        self._data: dict[str, bytes] = data if data is not None else {}
        # Shared across namespaced views so the test can inspect writes.
        self.set_calls: list[tuple[str, Any]] = (
            set_calls if set_calls is not None else []
        )

    def with_namespace(self, namespace: str) -> 'FakeRedisStore':
        # Share the backing dict + call log so the namespaced view is observable.
        return FakeRedisStore(
            f'{self.namespace}_{namespace}', self._data, self.set_calls
        )

    def _key(self, key: str) -> str:
        return f'{self.namespace}:{key}'

    async def get(self, key: str, renew_for=None) -> bytes | None:
        return self._data.get(self._key(key))

    async def set(self, key: str, value: str | bytes, expires_in=None) -> None:
        if isinstance(value, str):
            value = value.encode()
        self.set_calls.append((self._key(key), expires_in))
        self._data[self._key(key)] = value


async def test_get_missing_returns_none() -> None:
    repo = RedisCircuitBreakerRepository(FakeRedisStore())
    assert await repo.get('kaspa-rpc') is None


async def test_save_then_get_round_trips() -> None:
    store = FakeRedisStore()
    repo = RedisCircuitBreakerRepository(store, key_prefix='cb', ttl_seconds=120)

    snap = CircuitBreakerSnapshot(
        name='kaspa-rpc', state=CircuitState.OPEN, failure_count=5, opened_at=123.0
    )
    await repo.save(snap)

    loaded = await repo.get('kaspa-rpc')
    assert loaded is not None
    assert loaded.name == 'kaspa-rpc'
    assert loaded.state is CircuitState.OPEN
    assert loaded.failure_count == 5
    assert loaded.opened_at == 123.0

    # Stored under the dedicated namespace with the configured TTL.
    assert store.set_calls and store.set_calls[0][1] == 120


async def test_corrupt_value_is_treated_as_absent() -> None:
    store = FakeRedisStore()
    repo = RedisCircuitBreakerRepository(store)
    # Write garbage directly under the namespaced key the repo will read.
    namespaced = store.with_namespace('cb')
    await namespaced.set('snapshot:x', b'not-json')

    assert await repo.get('x') is None
