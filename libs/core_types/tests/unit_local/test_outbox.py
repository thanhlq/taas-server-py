"""Tests for `core_types.resilience.outbox`."""

from __future__ import annotations

import pytest

from core_types.resilience.outbox import (
    IOutboxPublisher,
    IOutboxRepository,
    OutboxConfig,
    OutboxFactory,
    OutboxMessage,
    OutboxService,
    OutboxStatus,
)


class InMemoryOutboxRepository(IOutboxRepository):
    def __init__(self) -> None:
        self._store: dict[str, OutboxMessage] = {}

    async def enqueue(self, message: OutboxMessage) -> None:
        self._store[message.id] = message

    async def fetch_pending(self, *, limit: int):
        return [m for m in self._store.values() if m.status is OutboxStatus.PENDING][
            :limit
        ]

    async def mark_published(self, message_id: str, *, published_at: float) -> None:
        m = self._store[message_id]
        m.status = OutboxStatus.PUBLISHED
        m.published_at = published_at

    async def mark_failed(
        self, message_id: str, *, attempts: int, error: str, terminal: bool
    ) -> None:
        m = self._store[message_id]
        m.attempts = attempts
        m.last_error = error
        m.status = OutboxStatus.FAILED if terminal else OutboxStatus.PENDING


class CapturingPublisher(IOutboxPublisher):
    def __init__(self, fail_times: int = 0) -> None:
        self.published: list[OutboxMessage] = []
        self._remaining_failures = fail_times

    async def publish(self, message: OutboxMessage) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("broker down")
        self.published.append(message)


@pytest.fixture
def repo() -> InMemoryOutboxRepository:
    return InMemoryOutboxRepository()


async def test_enqueue_persists_pending(repo: InMemoryOutboxRepository) -> None:
    service = OutboxService(repo, CapturingPublisher())
    msg = await service.enqueue("topic.a", b"payload")
    assert msg.status is OutboxStatus.PENDING
    assert (await repo.fetch_pending(limit=10))[0].id == msg.id


async def test_relay_publishes_pending_messages(
    repo: InMemoryOutboxRepository,
) -> None:
    publisher = CapturingPublisher()
    service = OutboxService(repo, publisher)

    for i in range(3):
        await service.enqueue("topic.a", f"p{i}".encode())

    published = await service.relay_once()
    assert published == 3
    assert {m.payload for m in publisher.published} == {b"p0", b"p1", b"p2"}
    assert await repo.fetch_pending(limit=10) == []


async def test_relay_handles_transient_failure(
    repo: InMemoryOutboxRepository,
) -> None:
    publisher = CapturingPublisher(fail_times=1)
    service = OutboxService(repo, publisher, OutboxConfig(max_attempts=5))
    await service.enqueue("topic.a", b"p")

    assert await service.relay_once() == 0  # failure -> back to pending
    assert await service.relay_once() == 1  # retry succeeds


async def test_relay_marks_terminal_after_max_attempts(
    repo: InMemoryOutboxRepository,
) -> None:
    publisher = CapturingPublisher(fail_times=99)
    service = OutboxService(repo, publisher, OutboxConfig(max_attempts=2))
    await service.enqueue("topic.a", b"p")

    await service.relay_once()  # attempt 1, fails -> pending
    await service.relay_once()  # attempt 2, fails -> FAILED

    pending = await repo.fetch_pending(limit=10)
    assert pending == []


async def test_factory_builds_service(repo: InMemoryOutboxRepository) -> None:
    factory = OutboxFactory(repo, CapturingPublisher())
    assert isinstance(factory.create_service(), OutboxService)
