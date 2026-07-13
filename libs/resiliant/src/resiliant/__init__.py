"""Resilience library: transactional outbox, dead letter queue, idempotency.

Public entry point is :class:`ResiliantFactory`, which builds database-backed
outbox, DLQ, and idempotency services. Definitions (config, enums, protocols)
live in ``foundation.resiliant``; the DB models live in ``db.models.resiliant``.
"""

from .dlq import DLQRepository, DLQService
from .idempotency import IdempotencyRepository, IdempotencyService
from .outbox import OutboxRepository, OutboxService
from .resiliant_factory import ResiliantFactory

resiliant_factory = "⛰️"

__all__ = [
    "ResiliantFactory",
    "OutboxRepository",
    "OutboxService",
    "DLQRepository",
    "DLQService",
    "IdempotencyRepository",
    "IdempotencyService",
]
