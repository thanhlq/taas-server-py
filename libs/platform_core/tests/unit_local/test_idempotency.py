"""Tests for `platform_core.resilience.idempotency`."""

from __future__ import annotations

import asyncio

import pytest

from platform_core.resilience.idempotency import (
    IIdempotencyRepository,
    IdempotencyConfig,
    IdempotencyConflictError,
    IdempotencyError,
    IdempotencyFactory,
    IdempotencyInProgressError,
    IdempotencyRecord,
    IdempotencyService,
    IdempotencyStatus,
)


class InMemoryIdempotencyRepository(IIdempotencyRepository):
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        namespace: str,
        record: IdempotencyRecord,
        *,
        ttl_seconds: int,
    ) -> IdempotencyRecord:
        async with self._lock:
            key = (namespace, record.key)
            existing = self._store.get(key)
            if existing is not None:
                return existing
            self._store[key] = record
            return record

    async def get(self, namespace: str, key: str) -> IdempotencyRecord | None:
        return self._store.get((namespace, key))

    async def complete(
        self,
        namespace: str,
        key: str,
        *,
        response: bytes,
        completed_at: float,
        ttl_seconds: int,
    ) -> None:
        async with self._lock:
            record = self._store[(namespace, key)]
            self._store[(namespace, key)] = IdempotencyRecord(
                key=record.key,
                status=IdempotencyStatus.COMPLETED,
                created_at=record.created_at,
                completed_at=completed_at,
                fingerprint=record.fingerprint,
                response=response,
            )

    async def fail(self, namespace: str, key: str) -> None:
        async with self._lock:
            self._store.pop((namespace, key), None)


@pytest.fixture
def repo() -> InMemoryIdempotencyRepository:
    return InMemoryIdempotencyRepository()


@pytest.fixture
def service(repo: InMemoryIdempotencyRepository) -> IdempotencyService:
    return IdempotencyService(repo, IdempotencyConfig(namespace="test"))


async def test_executes_handler_once_and_caches_response(
    service: IdempotencyService,
) -> None:
    calls = 0

    async def handler() -> bytes:
        nonlocal calls
        calls += 1
        return b"hello"

    r1 = await service.execute("k1", handler)
    r2 = await service.execute("k1", handler)

    assert r1 == b"hello"
    assert r2 == b"hello"
    assert calls == 1


async def test_different_keys_run_independently(service: IdempotencyService) -> None:
    async def make(value: bytes):
        async def h() -> bytes:
            return value

        return h

    r1 = await service.execute("k1", await make(b"a"))
    r2 = await service.execute("k2", await make(b"b"))
    assert (r1, r2) == (b"a", b"b")


async def test_handler_failure_releases_reservation(
    service: IdempotencyService,
) -> None:
    async def boom() -> bytes:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        await service.execute("k1", boom)

    async def ok() -> bytes:
        return b"ok"

    # Reservation was released; the key is retriable.
    assert await service.execute("k1", ok) == b"ok"


async def test_fingerprint_mismatch_raises_conflict(
    service: IdempotencyService,
) -> None:
    async def h() -> bytes:
        return b"ok"

    await service.execute("k1", h, request_payload=b"payload-A")

    with pytest.raises(IdempotencyConflictError):
        await service.execute("k1", h, request_payload=b"payload-B")


async def test_concurrent_in_progress_raises(
    repo: InMemoryIdempotencyRepository,
) -> None:
    service = IdempotencyService(repo, IdempotencyConfig(namespace="t"))
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow() -> bytes:
        started.set()
        await release.wait()
        return b"done"

    task = asyncio.create_task(service.execute("k1", slow))
    await started.wait()

    async def quick() -> bytes:
        return b"x"

    with pytest.raises(IdempotencyInProgressError):
        await service.execute("k1", quick)

    release.set()
    assert await task == b"done"


async def test_factory_builds_service(
    repo: InMemoryIdempotencyRepository,
) -> None:
    factory = IdempotencyFactory(repo, IdempotencyConfig(namespace="f"))
    svc = factory.create_service()
    assert isinstance(svc, IdempotencyService)
    assert svc.config.namespace == "f"


async def test_get_returns_completed_record(service: IdempotencyService) -> None:
    async def h() -> bytes:
        return b"data"

    await service.execute("k1", h)
    record = await service.get("k1")
    assert record is not None
    assert record.status is IdempotencyStatus.COMPLETED
    assert record.response == b"data"


async def test_completed_without_response_raises(
    repo: InMemoryIdempotencyRepository,
) -> None:
    # Corrupt record: COMPLETED but no response.
    await repo.reserve(
        "ns",
        IdempotencyRecord(
            key="k", status=IdempotencyStatus.COMPLETED, created_at=0.0
        ),
        ttl_seconds=60,
    )
    service = IdempotencyService(repo, IdempotencyConfig(namespace="ns"))

    async def h() -> bytes:
        return b""

    with pytest.raises(IdempotencyError):
        await service.execute("k", h)
