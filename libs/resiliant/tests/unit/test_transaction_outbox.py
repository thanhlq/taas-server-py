"""Transaction outbox + per-use-case factory (real database, see ``conftest.py``)."""

from __future__ import annotations

import pytest
from foundation.resiliant.outbox import OutboxConfig, OutboxName, OutboxStatus, OutboxTarget
from resiliant import ResiliantServiceBuilder, ResiliantServiceFactory
from resiliant.models import MessagingOutboxTable, TransactionOutboxTable
from resiliant.outbox import TransactionOutboxService, get_outbox_definition
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def service() -> TransactionOutboxService:
    return ResiliantServiceBuilder.build_transaction_outbox_service(
        OutboxTarget.MESSAGING, OutboxConfig(batch_size=10, max_retries=2)
    )


def test_factory_returns_one_service_per_use_case() -> None:
    factory = ResiliantServiceFactory()
    messaging = factory.get_messaging_outbox_service()
    transaction = factory.get_transaction_outbox_service(target=OutboxTarget.MESSAGING)

    assert messaging.repository.model is MessagingOutboxTable  # type: ignore[attr-defined]
    assert transaction.repository.model is TransactionOutboxTable  # type: ignore[attr-defined]
    assert transaction.target == OutboxTarget.MESSAGING  # type: ignore[attr-defined]
    # Cached per use case / target; `get_outbox_service` stays the messaging alias.
    assert factory.get_transaction_outbox_service(OutboxTarget.MESSAGING) is transaction
    assert factory.get_outbox_service() is messaging


def test_registry_knows_the_builtin_outboxes() -> None:
    assert get_outbox_definition(OutboxName.MESSAGING).model is MessagingOutboxTable
    assert get_outbox_definition(OutboxName.TRANSACTION).model is TransactionOutboxTable
    with pytest.raises(KeyError, match='registered'):
        get_outbox_definition('does-not-exist')


async def test_save_transaction_persists_in_its_own_table(
    db_session: AsyncSession, service: TransactionOutboxService
) -> None:
    row = await service.save_transaction(
        db_session,
        request_id='req-1',
        transaction_type='deposit',
        payload={'amount': '10.00', 'currency': 'EUR'},
        channel='transactions.inbound',
        account_ref='acc-42',
        source_system='partner-api',
    )
    await db_session.commit()

    assert isinstance(row, TransactionOutboxTable)
    assert row.status == OutboxStatus.PENDING
    assert row.target == OutboxTarget.MESSAGING
    assert row.transaction_type == 'deposit'
    # One account's requests stay ordered by default.
    assert row.ordering_key == 'acc-42'
    assert (await service.get_stats(db_session))['pending'] == 1
    # Nothing leaked into the messaging outbox.
    count = await db_session.scalar(select(func.count()).select_from(MessagingOutboxTable))
    assert count == 0


async def test_save_transaction_is_idempotent_on_request_id(
    db_session: AsyncSession, service: TransactionOutboxService
) -> None:
    first = await service.save_transaction(
        db_session, request_id='req-dup', transaction_type='transfer', payload={'n': 1}, channel='tx'
    )
    await db_session.commit()
    again = await service.save_transaction(
        db_session, request_id='req-dup', transaction_type='transfer', payload={'n': 2}, channel='tx'
    )

    assert again.id == first.id
    assert again.payload == {'n': 1}
    assert (await service.get_stats(db_session))['pending'] == 1
