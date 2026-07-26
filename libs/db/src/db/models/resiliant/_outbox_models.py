"""
Outbox database models and types.
"""
from datetime import datetime
from typing import Any, Dict

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.mixins import AuditColumns
from foundation.resiliant.outbox import OutboxStatus

# from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Column,
    Enum,
    Index,
    Integer,
    String,
    # Do not use this, use TIMESTAMP
    # DateTime,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.config import RESILIANT_TABLE_PREFIX

# from .types import OutboxStatus


class OutboxEventTable(UUIDv7AuditBase):
    """
    Outbox event model for reliable event publishing.

    This table stores events that need to be published to messaging systems.
    Events are inserted in the same transaction as business data, ensuring
    transactional guarantees.

    Note:
        The outbox relies on explicit archiving / hard-deletion (see
        ``OutboxEventArchiveTable`` and the repository ``archive_*`` / cleanup
        routines) rather than soft-deletion, so no ``deleted_at`` column is
        used here.

    Indexes:
        - idx_outbox_pending: Fast lookup for pending events
        - idx_outbox_processing: Track processing events
        - idx_outbox_created: Time-based queries and archiving
        - idx_outbox_status_retry: Efficient retry logic
    """

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}outbox_events'

    # Event identification
    event_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(255), nullable=False, index=True)

    # Kafka/messaging details
    channel = Column(String(255), nullable=False)
    ordering_key = Column(String(255), nullable=True)
    """Optional key for Kafka partitioning (e.g., user_id, tenant_id)"""

    # Event payload
    payload = Column(JSON, nullable=False)
    """JSON payload of the event"""

    headers = Column(JSON, nullable=True, default=dict)
    """Optional headers for the message (e.g., correlation_id, trace_id)"""

    # Status tracking
    status = Column(
        Enum(OutboxStatus), nullable=False, default=OutboxStatus.PENDING, index=True
    )
    # status: Mapped[OutboxStatus] = mapped_column(
    #     Enum(OutboxStatus), nullable=False, index=True
    # )
    # status = Column(
    #     String(20), nullable=False, index=True
    # )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Error tracking
    last_error = Column(Text, nullable=True)
    """Last error message if publishing failed"""

    # Timestamps
    # created_at = Column(DateTime, nullable=False, default=now_in_utc, index=True)
    # updated_at = Column(
    #     DateTime, nullable=False, default=now_in_utc, onupdate=now_in_utc
    # )

    # processed_at = Column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=False), nullable=True
    )
    # default=lambda: datetime.datetime.now(datetime.timezone.utc),
    """When the event was successfully published"""

    # Metadata
    source_service = Column(String(100), nullable=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(64), nullable=True)

    # Indexes for performance
    __table_args__ = (
        # Critical indexes for polling (FIXME - revisit these)
        # Index(
        #     'idx_outbox_pending',
        #     'status',
        #     'created_at',
        #     postgresql_where=(Column('status') == OutboxStatus.PENDING.value),
        # ),
        # Index(
        #     'idx_outbox_processing',
        #     'status',
        #     'updated_at',
        #     postgresql_where=(
        #         Column('status').in_([OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value])
        #     ),
        # ),
        Index(
            'idx_outbox_status_retry',
            'status',
            'retry_count',
            'created_at',
        ),
        # For archiving and cleanup
        Index('idx_outbox_status_created', 'status', 'created_at'),
    )

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'event_id': self.event_id,
            'event_type': self.event_type,
            'channel': self.channel,
            'ordering_key': self.ordering_key,
            'payload': self.payload,
            'headers': self.headers,
            'status': self.status,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'last_error': self.last_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'processed_at': self.processed_at.isoformat()
            if self.processed_at
            else None,
            'source_service': self.source_service,
            'correlation_id': self.correlation_id,
            'user_id': self.user_id,
        }


class OutboxEventArchiveTable(AuditColumns):
    """
    Archive table for published/processed outbox events.

    Events are moved here after successful publishing to keep the main
    outbox table small and performant.
    """

    __tablename__ = 'outbox_events_archive'

    # Same structure as OutboxEvent
    # id = Column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(
        Text,
        # server_default=text('gen_random_uuid()'),
        primary_key=True,
    )

    event_id = Column(String(64), nullable=False)
    event_type = Column(String(255), nullable=False, index=True)
    channel = Column(String(255), nullable=False)
    ordering_key = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=False)
    headers = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, index=True)
    retry_count = Column(Integer, nullable=False)
    max_retries = Column(Integer, nullable=False)
    last_error = Column(Text, nullable=True)
    # created_at = Column(DateTime, nullable=False, index=True)
    # updated_at = Column(DateTime, nullable=False)
    processed_at = Column(TIMESTAMP(timezone=False), nullable=True)
    archived_at = Column(TIMESTAMP(timezone=False), nullable=False, default=func.now())
    source_service = Column(String(100), nullable=True)
    correlation_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=True)

    __table_args__ = (
        # Index('idx_outbox_archive_created', 'created_at'),
        Index('idx_outbox_archive_archived', 'archived_at'),
    )
