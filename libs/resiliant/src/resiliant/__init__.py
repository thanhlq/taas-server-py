"""Resilience library: transactional outbox and dead letter queue.

Public entry point is :class:`ResiliantFactory`, which builds database-backed
outbox and DLQ services. Definitions (config, enums, protocols) live in
``foundation.resiliant``; the DB models live in ``db.models.resiliant``.
"""

from .dlq import DLQRepository, DLQService
from .outbox import OutboxRepository, OutboxService
from .resiliant_factory import ResiliantFactory

resiliant_factory = "⛰️"

__all__ = [
    "ResiliantFactory",
    "OutboxRepository",
    "OutboxService",
    "DLQRepository",
    "DLQService",
]
