"""
Outbox metrics tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from foundation.utils import now_in_utc


@dataclass
class OutboxMetrics:
    """
    Metrics for outbox pattern performance tracking.
    """

    # Polling metrics
    total_polls: int = 0
    empty_polls: int = 0
    successful_polls: int = 0
    failed_polls: int = 0

    # Processing metrics
    total_events_processed: int = 0
    total_events_published: int = 0
    total_events_failed: int = 0
    total_events_moved_to_dlq: int = 0

    # Performance metrics
    min_poll_duration_ms: Optional[float] = None
    max_poll_duration_ms: Optional[float] = None
    avg_poll_duration_ms: float = 0.0

    min_publish_duration_ms: Optional[float] = None
    max_publish_duration_ms: Optional[float] = None
    avg_publish_duration_ms: float = 0.0

    # Batch metrics
    min_batch_size: Optional[int] = None
    max_batch_size: Optional[int] = None
    avg_batch_size: float = 0.0

    # Current state
    current_poll_interval_ms: float = 500.0
    last_poll_time: Optional[datetime] = None

    # Database metrics
    stale_events_reset: int = 0
    events_archived: int = 0
    archive_cleaned: int = 0

    # Start time
    started_at: datetime = field(default_factory=now_in_utc)

    def record_poll(
        self,
        duration_ms: float,
        batch_size: int,
        success: bool,
    ) -> None:
        """Record poll metrics."""
        self.total_polls += 1

        if batch_size == 0:
            self.empty_polls += 1

        if success:
            self.successful_polls += 1
        else:
            self.failed_polls += 1

        # Update poll duration
        if self.min_poll_duration_ms is None:
            self.min_poll_duration_ms = duration_ms
        else:
            self.min_poll_duration_ms = min(self.min_poll_duration_ms, duration_ms)

        if self.max_poll_duration_ms is None:
            self.max_poll_duration_ms = duration_ms
        else:
            self.max_poll_duration_ms = max(self.max_poll_duration_ms, duration_ms)

        # Update average
        self.avg_poll_duration_ms = (
            self.avg_poll_duration_ms * (self.total_polls - 1) + duration_ms
        ) / self.total_polls

        # Update batch size
        if batch_size > 0:
            if self.min_batch_size is None:
                self.min_batch_size = batch_size
            else:
                self.min_batch_size = min(self.min_batch_size, batch_size)

            if self.max_batch_size is None:
                self.max_batch_size = batch_size
            else:
                self.max_batch_size = max(self.max_batch_size, batch_size)

            successful_batches = self.total_polls - self.empty_polls
            self.avg_batch_size = (
                self.avg_batch_size * (successful_batches - 1) + batch_size
            ) / successful_batches

        self.last_poll_time = now_in_utc()

    def record_publish(
        self,
        duration_ms: float,
        success: bool,
        moved_to_dlq: bool = False,
    ) -> None:
        """Record publish metrics."""
        self.total_events_processed += 1

        if success:
            self.total_events_published += 1
        else:
            self.total_events_failed += 1

        if moved_to_dlq:
            self.total_events_moved_to_dlq += 1

        # Update publish duration
        if success:
            if self.min_publish_duration_ms is None:
                self.min_publish_duration_ms = duration_ms
            else:
                self.min_publish_duration_ms = min(
                    self.min_publish_duration_ms, duration_ms
                )

            if self.max_publish_duration_ms is None:
                self.max_publish_duration_ms = duration_ms
            else:
                self.max_publish_duration_ms = max(
                    self.max_publish_duration_ms, duration_ms
                )

            # Update average
            if self.total_events_published > 0:
                self.avg_publish_duration_ms = (
                    self.avg_publish_duration_ms * (self.total_events_published - 1)
                    + duration_ms
                ) / self.total_events_published

    def empty_poll_rate(self) -> float:
        """Calculate empty poll rate."""
        return (
            (self.empty_polls / self.total_polls * 100) if self.total_polls > 0 else 0.0
        )

    def success_rate(self) -> float:
        """Calculate publish success rate."""
        return (
            (self.total_events_published / self.total_events_processed * 100)
            if self.total_events_processed > 0
            else 0.0
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/monitoring."""
        uptime_seconds = (now_in_utc() - self.started_at).total_seconds()

        return {
            # Polling
            'total_polls': self.total_polls,
            'empty_polls': self.empty_polls,
            'empty_poll_rate': f'{self.empty_poll_rate():.1f}%',
            'successful_polls': self.successful_polls,
            'failed_polls': self.failed_polls,
            # Processing
            'total_events_processed': self.total_events_processed,
            'total_events_published': self.total_events_published,
            'total_events_failed': self.total_events_failed,
            'total_events_dlq': self.total_events_moved_to_dlq,
            'success_rate': f'{self.success_rate():.1f}%',
            # Performance
            'poll_duration_ms': {
                'min': self.min_poll_duration_ms,
                'max': self.max_poll_duration_ms,
                'avg': f'{self.avg_poll_duration_ms:.2f}',
            },
            'publish_duration_ms': {
                'min': self.min_publish_duration_ms,
                'max': self.max_publish_duration_ms,
                'avg': f'{self.avg_publish_duration_ms:.2f}',
            },
            'batch_size': {
                'min': self.min_batch_size,
                'max': self.max_batch_size,
                'avg': f'{self.avg_batch_size:.1f}',
            },
            # Current state
            'current_poll_interval_ms': f'{self.current_poll_interval_ms:.0f}',
            'throughput_per_sec': (
                f'{self.total_events_published / uptime_seconds:.2f}'
                if uptime_seconds > 0
                else '0.00'
            ),
            # Database
            'stale_events_reset': self.stale_events_reset,
            'uptime_seconds': f'{uptime_seconds:.0f}',
        }
