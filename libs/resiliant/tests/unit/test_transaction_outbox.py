"""Transaction outbox: idempotent on ``request_id`` (real database)."""

from __future__ import annotations

from foundation.resiliant.outbox import OutboxConfig, OutboxStatus
from resiliant.outbox.factory import build_transaction_outbox_service
from sqlalchemy.ext.asyncio import AsyncSession


async def test_repeated_request_id_returns_the_stored_record(
    db_session: AsyncSession,
) -> None:
    service = build_transaction_outbox_service(config=OutboxConfig(max_retries=3))
    first = await service.save_transaction(
        db_session,
        request_id='req-1',
        transaction_type='deposit',
        payload={'amount': 10},
        account_ref='acc-9',
    )
    again = await service.save_transaction(
        db_session,
        request_id='req-1',
        transaction_type='deposit',
        payload={'amount': 99},
    )
    assert first.id == again.id
    assert again.payload == {'amount': 10}
    assert first.ordering_key == 'acc-9'  # account ref is the default ordering key
    assert first.transaction_type == 'deposit' and first.status == OutboxStatus.PENDING
