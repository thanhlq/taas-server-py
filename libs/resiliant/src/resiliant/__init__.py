"""Resilience library: transactional outbox, dead letter queue, idempotency.

Public entry point is :class:`ResiliantFactory`, which builds database-backed
outbox, DLQ, and idempotency services. Definitions (config, enums, protocols)
live in ``foundation.resiliant``; the DB models live in ``db.models.resiliant``.
"""

from .dlq import DLQRepository, DLQService
from .factory import ResiliantServiceFactory
from .idempotency import IdempotencyRepository, IdempotencyService
from .outbox import OutboxRepository, OutboxService
from .service_builder import ResiliantServiceBuilder

service_builder = "⛰️"

__all__: list[str] = [
    "ResiliantServiceBuilder",
    "ResiliantServiceFactory",
    "OutboxRepository",
    "OutboxService",
    "DLQRepository",
    "DLQService",
    "IdempotencyRepository",
    "IdempotencyService",
]
