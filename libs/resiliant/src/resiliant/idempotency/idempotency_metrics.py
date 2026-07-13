"""
Idempotency metrics — in-process counters for the idempotency subsystem.

These are lightweight counters held in memory. They are not persisted and
reset on process restart. Wire them into a metrics exporter (Prometheus,
StatsD, CloudWatch, …) by reading the fields at scrape time via
:meth:`IdempotencyMetrics.snapshot`.

No locking is used: Python's GIL makes simple integer increments safe within
a single process, and the counters are advisory rather than authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from foundation.utils import now_in_utc


@dataclass
class IdempotencyMetrics:
    """In-process counters for the idempotency subsystem.

    Attributes
    ----------
    total_checks:      Cumulative idempotency-key lookups performed.
    total_processed:   Cumulative events recorded as processed (INSERT won).
    total_duplicates:  Cumulative duplicate events detected.
    total_errors:      Cumulative exceptions raised inside guarded blocks.
    total_cleaned_up:  Cumulative expired rows deleted by cleanup runs.
    last_duplicate_key: Most-recently detected duplicate key (for alerting).
    last_error_at:     Timestamp of the most recent guarded-block error.
    started_at:        When this metrics instance was created.
    """

    # Throughput counters
    total_checks: int = 0
    total_processed: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    total_cleaned_up: int = 0

    # Diagnostic fields
    last_duplicate_key: Optional[str] = None
    last_error_at: Optional[datetime] = None

    # Lifecycle
    started_at: datetime = field(default_factory=now_in_utc)

    # ------------------------------------------------------------------
    # record_* helpers (called by IdempotencyService)
    # ------------------------------------------------------------------

    def record_check(self) -> None:
        """Increment the total number of idempotency key checks."""
        self.total_checks += 1

    def record_processed(self) -> None:
        """Increment processed counter when a key is newly recorded."""
        self.total_processed += 1

    def record_duplicate(self, key: Optional[str] = None) -> None:
        """Increment duplicate counter and optionally track the last key."""
        self.total_duplicates += 1
        if key:
            self.last_duplicate_key = key

    def record_error(self) -> None:
        """Increment error counter and note the timestamp."""
        self.total_errors += 1
        self.last_error_at = now_in_utc()

    def record_cleanup(self, rows_deleted: int) -> None:
        """Accumulate rows deleted by a cleanup run."""
        self.total_cleaned_up += rows_deleted

    # ------------------------------------------------------------------
    # Snapshot helpers (useful for exporters)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return a plain-dict snapshot of all counter values."""
        return {
            'total_checks': self.total_checks,
            'total_processed': self.total_processed,
            'total_duplicates': self.total_duplicates,
            'total_errors': self.total_errors,
            'total_cleaned_up': self.total_cleaned_up,
            'last_duplicate_key': self.last_duplicate_key,
            'last_error_at': (
                self.last_error_at.isoformat() if self.last_error_at else None
            ),
            'started_at': self.started_at.isoformat(),
        }

    @property
    def duplicate_rate(self) -> float:
        """Fraction of checks that detected a duplicate (0.0 – 1.0)."""
        return self.total_duplicates / self.total_checks if self.total_checks else 0.0

    @property
    def error_rate(self) -> float:
        """Fraction of processed events that resulted in an error (0.0 – 1.0)."""
        denominator = self.total_processed + self.total_errors
        return self.total_errors / denominator if denominator else 0.0
