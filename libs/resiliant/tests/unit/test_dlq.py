"""Unit tests for the DLQ repository and service (via ``ResiliantFactory``).

These exercise the real database (see ``conftest.py``): save → list → fetch →
resolve / fail / abandon, and the stats projection.
"""

from __future__ import annotations

import pytest
from foundation.resiliant.dlq import DeadLetterConfig, DLQStatus
from resiliant import ResiliantFactory
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def config() -> DeadLetterConfig:
    return DeadLetterConfig(batch_size=10, page_size=50, max_retries=2)


async def _save(service, session: AsyncSession, **overrides):
    payload = {
        "event_id": "evt-1",
        "event_type": "OrderCreated",
        "handler_name": "OrderHandler",
        "payload": {"order_id": "o-1"},
        "error": "Downstream timeout",
    }
    payload.update(overrides)
    return await service.save_event(session, **payload)


async def test_factory_builds_dlq_components(config: DeadLetterConfig) -> None:
    service = ResiliantFactory.get_dlq_service(config)
    repo = ResiliantFactory.get_dlq_repository(config)
    assert service.config.max_retries == 2
    assert repo.config.page_size == 50


async def test_save_event_persists_pending(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)

    row = await _save(service, db_session)

    assert row.id is not None
    assert row.status == DLQStatus.PENDING
    assert row.handler_name == "OrderHandler"
    assert row.original_error == "Downstream timeout"
    assert row.failed_at is not None

    assert (await service.get_stats(db_session))["pending"] == 1


async def test_get_and_list(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)

    a = await _save(service, db_session, handler_name="OrderHandler")
    await _save(service, db_session, handler_name="EmailHandler")

    fetched = await service.get(db_session, a.id)
    assert fetched is not None
    assert fetched.id == a.id

    assert len(await service.list(db_session)) == 2
    assert len(await service.list(db_session, handler_name="OrderHandler")) == 1
    assert len(await service.list_pending(db_session)) == 2


async def test_fetch_pending_batch_marks_processing(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)
    repo = ResiliantFactory.get_dlq_repository(config)

    for i in range(3):
        await _save(service, db_session, event_id=f"evt-{i}")

    batch = await repo.fetch_pending_batch(db_session, batch_size=10)

    assert len(batch) == 3
    assert all(e.status == DLQStatus.PROCESSING for e in batch)


async def test_resolve_marks_resolved(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)

    row = await _save(service, db_session)
    await service.resolve(db_session, row.id)

    stats = await service.get_stats(db_session)
    assert stats["resolved"] == 1
    assert stats["pending"] == 0


async def test_fail_retries_then_abandons(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)

    row = await _save(service, db_session, max_retries=2)

    # First failure -> back to PENDING for another attempt.
    await service.fail(db_session, row.id, error="still broken")
    assert (await service.get_stats(db_session))["pending"] == 1

    # Second failure exhausts the budget -> ABANDONED.
    await service.fail(db_session, row.id, error="broken again")
    stats = await service.get_stats(db_session)
    assert stats["abandoned"] == 1
    assert stats["pending"] == 0


async def test_abandon_marks_abandoned(
    db_session: AsyncSession, config: DeadLetterConfig
) -> None:
    service = ResiliantFactory.get_dlq_service(config)

    row = await _save(service, db_session)
    await service.abandon(db_session, row.id)

    assert (await service.get_stats(db_session))["abandoned"] == 1
