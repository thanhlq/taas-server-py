"""
DLQ database models.

This module defines the SQLAlchemy models for storing failed events
in the Dead Letter Queue (DLQ) tables.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from advanced_alchemy.base import UUIDv7AuditBase
from foundation.resiliant.dlq import DLQStatus
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Column,
    Enum,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class DLQEventTable(UUIDv7AuditBase):
    """
    DLQ event model for failed message retry.

    This table stores events that failed processing after exceeding the
    maximum number of in-memory retries. Events stored here can be retried
    manually or automatically by the DLQ poller.

    Key Fields:
        handler_name: Critical for retry - specifies which handler to invoke
        original_error: The error that caused the initial failure
        last_error: The most recent retry error (if retry failed)
        status: Current state in the DLQ lifecycle

    Indexes:
        - idx_dlq_status_created: Fast lookup for pending events (polling)
        - idx_dlq_handler_name: Query by handler for analysis/batch retry
        - idx_dlq_event_type: Query by event type
        - idx_dlq_status_retry: Efficient retry logic with status and retry_count

    Example:
        >>> dlq_event = DLQEventTable(
        ...     id=generate_id(),
        ...     event_id="evt_123",
        ...     event_type="OrderCreated",
        ...     handler_name="OrderHandler",
        ...     source_destination="orders.created",
        ...     payload={"order_id": "123", "amount": 99.99},
        ...     original_error="Database timeout",
        ...     status=DLQStatus.PENDING,
        ... )
        >>> session.add(dlq_event)
        >>> await session.commit()

    Note:
        This table should be kept small by archiving old events.
        Use archive_old_events() in the repository to move resolved/abandoned
        events to DLQEventArchiveTable.
    """

    __tablename__ = 'dlq_events'

    # Event identification
    event_id = Column(
        String(64),
        nullable=False,
        index=True,
        comment='Original event ID from the failed event',
    )

    event_type = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Type of the event (e.g., 'OrderCreated', 'UserUpdated')",
    )

    # Handler information (CRITICAL for retry)
    handler_name = Column(
        String(255),
        nullable=False,
        index=True,
        comment='Name of the handler that failed - used for targeted retry',
    )

    # Source information
    source_destination = Column(
        String(255),
        nullable=True,
        comment="Original source topic/queue (e.g., 'orders.created')",
    )

    source_service = Column(
        String(100),
        nullable=True,
        comment='Optional source service name',
    )

    # Event payload
    payload = Column(
        JSON,
        nullable=False,
        comment='Full event payload as JSON (used for retry)',
    )

    headers = Column(
        JSON,
        nullable=True,
        default=dict,
        comment='Event headers including trace context',
    )

    # Status tracking
    status = Column(
        Enum(DLQStatus),
        nullable=False,
        default=DLQStatus.PENDING,
        index=True,
        # comment='Current status in DLQ lifecycle',
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment='Number of retry attempts made',
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment='Maximum number of retries allowed',
    )

    # Error tracking
    original_error = Column(
        Text,
        nullable=False,
        comment='Error message from the initial failure',
    )

    last_error = Column(
        Text,
        nullable=True,
        comment='Error message from the most recent retry attempt',
    )

    # Metadata (optional but useful for filtering/analysis)
    correlation_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment='Correlation ID for tracing across services',
    )

    user_id = Column(
        String(64),
        nullable=True,
        comment='User ID associated with the event (if applicable)',
    )

    tenant_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        index=True,
        comment='Tenant ID for multi-tenant applications',
    )

    # Timestamps
    failed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False),
        nullable=False,
        comment='When the event originally failed',
    )

    # created_at: Mapped[datetime] = mapped_column(
    #     TIMESTAMP(timezone=False),
    #     server_default=text('NOW()'),
    #     nullable=False,
    #     index=True,
    #     comment='When the DLQ record was created',
    # )

    # updated_at: Mapped[datetime] = mapped_column(
    #     TIMESTAMP(timezone=False),
    #     server_default=text('NOW()'),
    #     onupdate=text('NOW()'),
    #     nullable=False,
    #     comment='When the DLQ record was last updated',
    # )

    processed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=False),
        nullable=True,
        comment='When the event was successfully reprocessed (resolved)',
    )

    # Composite indexes for efficient querying
    # __table_args__ = (
    #     # Most important: Fast lookup for pending events (used by poller)
    #     Index(
    #         'idx_dlq_status_created',
    #         'status',
    #         'created_at',
    #         comment='Fast lookup for pending events ordered by age',
    #     ),
    #     # For retry logic: status + retry_count
    #     Index(
    #         'idx_dlq_status_retry',
    #         'status',
    #         'retry_count',
    #         'created_at',
    #         comment='Efficient retry logic with status and retry count',
    #     ),
    # )

    def as_dict(self) -> Dict[str, Any]:
        """
        Convert DLQ event to dictionary.

        Returns:
            Dictionary representation of the DLQ event

        Example:
            >>> dlq_dict = dlq_event.to_dict()
            >>> print(dlq_dict['handler_name'])
            'OrderHandler'
        """
        return {
            'id': self.id,
            'event_id': self.event_id,
            'event_type': self.event_type,
            'handler_name': self.handler_name,
            'source_destination': self.source_destination,
            'source_service': self.source_service,
            'payload': self.payload,
            'headers': self.headers,
            'status': self.status.value,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'original_error': self.original_error,
            'last_error': self.last_error,
            'correlation_id': self.correlation_id,
            'user_id': self.user_id,
            'tenant_id': self.tenant_id,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'processed_at': self.processed_at.isoformat()
            if self.processed_at
            else None,
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f'<DLQEvent(id={self.id}, event_type={self.event_type}, '
            f'handler={self.handler_name}, status={self.status})>'
        )


# Most important: Fast lookup for pending events (used by poller)
Index(
    'idx_dlq_status_created',
    DLQEventTable.status,
    DLQEventTable.created_at,
    # comment='Fast lookup for pending events ordered by age',
)
# For retry logic: status + retry_count
Index(
    'idx_dlq_status_retry',
    DLQEventTable.status,
    DLQEventTable.retry_count,
    DLQEventTable.created_at,
    # comment='Efficient retry logic with status and retry count',
)


class DLQEventArchiveTable(UUIDv7AuditBase):
    """
    Archive table for resolved/abandoned DLQ events.

    Events are moved here after successful retry (RESOLVED) or after being
    marked as not retriable (ABANDONED) to keep the main dlq_events table
    small and performant.

    This table has the same structure as DLQEventTable but with an additional
    archived_at timestamp.

    Archiving Strategy:
        - Archive events older than N days (configurable)
        - Archive RESOLVED and ABANDONED events
        - Keep PENDING and PROCESSING in main table
        - Run archive job periodically (daily recommended)

    Example:
        >>> # Archive old events
        >>> count = await dlq_repository.archive_old_events(
        ...     session=session,
        ...     older_than_days=30,
        ... )
        >>> print(f"Archived {count} events")

    Note:
        This is a historical record table. Events here should generally
        not be modified, only queried for analysis and audit purposes.
    """

    __tablename__ = 'dlq_events_archive'

    event_id = Column(String(64), nullable=False)
    event_type = Column(String(255), nullable=False)
    handler_name = Column(String(255), nullable=False)
    source_destination = Column(String(255), nullable=False)
    source_service = Column(String(100), nullable=True)
    payload = Column(JSON, nullable=False)
    headers = Column(JSON, nullable=True)
    status = Column(Enum(DLQStatus), nullable=False)
    retry_count = Column(Integer, nullable=False)
    max_retries = Column(Integer, nullable=False)
    original_error = Column(Text, nullable=False)
    last_error = Column(Text, nullable=True)
    correlation_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=True)
    tenant_id = Column(Text, nullable=True)
    failed_at = Column(TIMESTAMP(timezone=False), nullable=False)
    processed_at = Column(TIMESTAMP(timezone=False), nullable=True)

    # Archive timestamp
    archived_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False),
        server_default=text('NOW()'),
        nullable=False,
        comment='When the event was archived',
    )

    # Indexes for archive queries
    # __table_args__ = (
    #     Index(
    #         'idx_dlq_archive_status',
    #         'status',
    #         comment='Query by status in archive',
    #     ),
    #     Index(
    #         'idx_dlq_archive_archived_at',
    #         'archived_at',
    #         comment='Query by archive date',
    #     ),
    #     Index(
    #         'idx_dlq_archive_handler',
    #         'handler_name',
    #         comment='Query by handler in archive',
    #     ),
    # )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f'<DLQEventArchive(id={self.id}, event_type={self.event_type}, '
            f'status={self.status}, archived_at={self.archived_at})>'
        )


Index(
    'idx_dlq_archive_status',
    DLQEventArchiveTable.status,
)
Index(
    'idx_dlq_archive_archived_at',
    DLQEventArchiveTable.archived_at,
)
Index(
    'idx_dlq_archive_handler',
    DLQEventArchiveTable.handler_name,
)
