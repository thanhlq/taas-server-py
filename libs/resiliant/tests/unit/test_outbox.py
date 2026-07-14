"""Unit tests for the outbox repository and service (via ``ResiliantFactory``).

These exercise the real database (see ``conftest.py``): save → fetch → mark
published / failed, and the stats projection.
"""

from __future__ import annotations

import pytest
from db.models import OutboxEventTable
from foundation.resiliant.outbox import OutboxConfig, OutboxStatus
from resiliant import ResiliantServiceBuilder
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def config() -> OutboxConfig:
    # Small batch + low retry cap keeps the tests deterministic and fast.
    return OutboxConfig(batch_size=10, max_retries=2)


async def test_factory_builds_outbox_components(config: OutboxConfig) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)
    repo = ResiliantServiceBuilder.build_outbox_repository(config)
    assert service.config.max_retries == 2
    assert repo.config.batch_size == 10


async def test_save_raw_message_persists_pending(
    db_session: AsyncSession, config: OutboxConfig
) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)

    row = await service.save_raw_message(
        db_session,
        channel="orders",
        payload={"order_id": "o-1", "amount": 42},
        event_type="OrderCreated",
    )

    assert row.id is not None
    assert row.status == OutboxStatus.PENDING
    assert row.channel == "orders"

    stats = await service.get_stats(db_session)
    assert stats["pending"] == 1


async def test_save_event_duck_typed(
    db_session: AsyncSession, config: OutboxConfig
) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)

    class _Event:
        event_id = "evt-123"
        event_type = "UserRegistered"
        correlation_id = "corr-9"
        source = "auth-service"

        def as_dict(self) -> dict:
            return {"user_id": "u-1"}

    row: OutboxEventTable = await service.save_event(db_session, _Event(), channel="users")

    assert row.event_id == "evt-123"
    assert row.event_type == "UserRegistered"
    assert row.correlation_id == "corr-9"
    assert row.payload == {"user_id": "u-1"}
    # Metadata is copied into headers for the broker relay.
    assert row.headers["source"] == "auth-service"


async def test_fetch_pending_batch_marks_processing(
    db_session: AsyncSession, config: OutboxConfig
) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)
    repo = ResiliantServiceBuilder.build_outbox_repository(config)

    for i in range(3):
        await service.save_raw_message(
            db_session,
            channel="orders",
            payload={"i": i},
            event_type="OrderCreated",
        )

    batch = await repo.fetch_pending_batch(db_session, batch_size=10)

    assert len(batch) == 3
    assert all(e.status == OutboxStatus.PROCESSING for e in batch)
    # Nothing pending left after the batch was claimed.
    assert (await repo.get_stats(db_session))["pending"] == 0


async def test_mark_published_updates_status(
    db_session: AsyncSession, config: OutboxConfig
) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)
    repo = ResiliantServiceBuilder.build_outbox_repository(config)

    row = await service.save_raw_message(
        db_session, channel="orders", payload={}, event_type="OrderCreated"
    )
    await repo.fetch_pending_batch(db_session, batch_size=10)

    await repo.mark_published(db_session, row.id)

    stats = await repo.get_stats(db_session)
    assert stats["published"] == 1
    assert stats["pending"] == 0


async def test_mark_failed_retries_then_dead_letters(
    db_session: AsyncSession, config: OutboxConfig
) -> None:
    service = ResiliantServiceBuilder.build_outbox_service(config)
    repo = ResiliantServiceBuilder.build_outbox_repository(config)

    row = await service.save_raw_message(
        db_session,
        channel="orders",
        payload={},
        event_type="OrderCreated",
        max_retries=2,
    )
    await repo.fetch_pending_batch(db_session, batch_size=10)

    # First failure -> retriable FAILED.
    await repo.mark_failed(db_session, row.id, error="boom")
    assert (await repo.get_stats(db_session))["failed"] == 1

    # Second failure exhausts the budget -> DEAD_LETTER.
    await repo.mark_failed(db_session, row.id, error="boom again")
    stats = await repo.get_stats(db_session)
    assert stats["dead_letter"] == 1
    assert stats["failed"] == 0
