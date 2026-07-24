# Example
from abc import ABC
from datetime import UTC, datetime, timedelta
from typing import List

from core.db.common import ID_COLUMN_NAME
from core.db.engine import DBAsyncSession
from core.db.models import MessageOutboxOrm
from core.db.sa.db_manager import db_session_async
from core.db.sa.repository import DBBaseRepositoryAsync
from core.db.types import IRepositoryProvider
from core.messaging.outbox.models import MessageOutbox, MessageOutboxStatus
from sqlalchemy import select


class SaMessageOutboxRepository(DBBaseRepositoryAsync[MessageOutboxOrm, MessageOutbox], ABC):
    def __init__(self, factory: IRepositoryProvider = None):
        super().__init__(
            MessageOutboxOrm,
            MessageOutbox,
            id_column=ID_COLUMN_NAME,
            factory=factory
        )

    @db_session_async(commit=True)
    async def add(
        self,
        model,
        session: DBAsyncSession,
        *args,
        **kwargs,
    ):
        raw_session = getattr(session, '_session', session)
        return await self.add_async(model, raw_session, *args, **kwargs)

    @db_session_async
    async def get_pending_messages(
        self,
        batch_size: int = 100,
        session: DBAsyncSession = None
    ) -> List[MessageOutbox]:
        """
        Get messages that are pending
        Uses SKIP LOCKED to prevent contention between consumers.

        Also not to query from old partitions, we order by created_at and limit the batch size.
        Example:
            SELECT uuid
            FROM floin_message_outbox
            WHERE status = 'PENDING'
            AND created_at >= now() - interval '7 days'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 100;
        """
        cutoff = datetime.now() - timedelta(days=7)
        query = (
            select(MessageOutboxOrm)
            .where(
                MessageOutboxOrm.status == MessageOutboxStatus.PENDING.value,
                MessageOutboxOrm.created_at >= cutoff,
            )
            .order_by(MessageOutboxOrm.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        result = await session.execute(query)
        orm_models = result.scalars().all()

        return [self.from_orm(orm) for orm in orm_models]

    @db_session_async
    async def mark_as_sent_batch(
        self,
        message_ids: List[str],
        session: DBAsyncSession = None
    ) -> int:
        """Mark a message as successfully sent."""
        if not message_ids:
            return 0
        now = datetime.now(UTC)

        stmt = (
            MessageOutboxOrm.__table__.update()
            .where(
                MessageOutboxOrm.uuid.in_(message_ids),
            )
            .values(
                status=MessageOutboxStatus.SENT.value,
                updated_at=now
            )
        )

        result = await session.execute(stmt)
        return result.rowcount

    @db_session_async
    async def mark_as_failed_batch(
        self,
        message_ids: List[str],
        session: DBAsyncSession = None
    ) -> int:
        """Mark a batch of messages as failed."""
        if not message_ids:
            return 0
        now = datetime.now()

        stmt = (
            MessageOutboxOrm.__table__.update()
            .where(MessageOutboxOrm.uuid.in_(message_ids))
            .values(
                status=MessageOutboxStatus.FAILED.value,
                updated_at=now
            )
        )

        result = await session.execute(stmt)
        return result.rowcount
