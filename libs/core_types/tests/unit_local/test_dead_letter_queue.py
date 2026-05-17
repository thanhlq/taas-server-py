"""Tests for `core_types.resilience.dead_letter_queue`."""

from __future__ import annotations

import pytest

from core_types.resilience.dead_letter_queue import (
    DeadLetterError,
    DeadLetterMessage,
    DeadLetterQueueFactory,
    DeadLetterQueueService,
    DeadLetterReplayError,
    IDeadLetterReplayer,
    IDeadLetterRepository,
)


class InMemoryDLQRepository(IDeadLetterRepository):
    def __init__(self) -> None:
        self._store: dict[str, DeadLetterMessage] = {}

    async def enqueue(self, message: DeadLetterMessage) -> None:
        self._store[message.id] = message

    async def get(self, message_id: str) -> DeadLetterMessage | None:
        return self._store.get(message_id)

    async def list_messages(
        self, *, source: str | None = None, limit: int = 100
    ):
        items = list(self._store.values())
        if source is not None:
            items = [m for m in items if m.source == source]
        return items[:limit]

    async def delete(self, message_id: str) -> None:
        self._store.pop(message_id, None)


class CapturingReplayer(IDeadLetterReplayer):
    def __init__(self, *, fail: bool = False) -> None:
        self.replayed: list[DeadLetterMessage] = []
        self._fail = fail

    async def replay(self, message: DeadLetterMessage) -> None:
        if self._fail:
            raise RuntimeError("sink down")
        self.replayed.append(message)


@pytest.fixture
def repo() -> InMemoryDLQRepository:
    return InMemoryDLQRepository()


async def test_enqueue_persists_message(repo: InMemoryDLQRepository) -> None:
    service = DeadLetterQueueService(repo)
    msg = await service.enqueue(
        source="orders", payload=b"p", error="boom", attempts=3
    )
    assert msg.source == "orders"
    assert (await service.get(msg.id)) == msg


async def test_list_filters_by_source(repo: InMemoryDLQRepository) -> None:
    service = DeadLetterQueueService(repo)
    await service.enqueue(source="a", payload=b"", error="e", attempts=1)
    await service.enqueue(source="b", payload=b"", error="e", attempts=1)
    assert len(await service.list(source="a")) == 1
    assert len(await service.list()) == 2


async def test_replay_invokes_sink_and_deletes(
    repo: InMemoryDLQRepository,
) -> None:
    replayer = CapturingReplayer()
    service = DeadLetterQueueService(repo, replayer=replayer)
    msg = await service.enqueue(source="a", payload=b"p", error="e", attempts=1)

    await service.replay(msg.id)
    assert replayer.replayed[0].id == msg.id
    assert await service.get(msg.id) is None


async def test_replay_failure_keeps_message(
    repo: InMemoryDLQRepository,
) -> None:
    service = DeadLetterQueueService(repo, replayer=CapturingReplayer(fail=True))
    msg = await service.enqueue(source="a", payload=b"p", error="e", attempts=1)

    with pytest.raises(DeadLetterReplayError):
        await service.replay(msg.id)
    assert await service.get(msg.id) is not None


async def test_replay_without_replayer_raises(
    repo: InMemoryDLQRepository,
) -> None:
    service = DeadLetterQueueService(repo)
    msg = await service.enqueue(source="a", payload=b"p", error="e", attempts=1)
    with pytest.raises(DeadLetterError):
        await service.replay(msg.id)


async def test_replay_unknown_id_raises(repo: InMemoryDLQRepository) -> None:
    service = DeadLetterQueueService(repo, replayer=CapturingReplayer())
    with pytest.raises(DeadLetterError):
        await service.replay("missing")


async def test_purge_deletes_message(repo: InMemoryDLQRepository) -> None:
    service = DeadLetterQueueService(repo)
    msg = await service.enqueue(source="a", payload=b"p", error="e", attempts=1)
    await service.purge(msg.id)
    assert await service.get(msg.id) is None


async def test_factory_builds_service(repo: InMemoryDLQRepository) -> None:
    factory = DeadLetterQueueFactory(repo, replayer=CapturingReplayer())
    assert isinstance(factory.create_service(), DeadLetterQueueService)
