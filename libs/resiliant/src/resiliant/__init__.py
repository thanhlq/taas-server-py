"""Resilience library: transactional outboxes, DLQ, idempotency, sagas, schedules.

Public entry point is :class:`ResiliantServiceFactory`. Definitions (config, enums,
protocols) live in ``foundation.resiliant``; the implementations *and* their
SQLAlchemy models (``resiliant.models``) live in this package.
"""

from .dlq import DLQHandlerRegistry, DLQRepository, DLQRetryProcessor, DLQService
from .resiliant_factory import ResiliantServiceFactory
from .idempotency import IdempotencyRepository, IdempotencyService
from .outbox import (
    MessagingOutboxService,
    OutboxDefinition,
    OutboxRepository,
    OutboxService,
    TransactionOutboxService,
    register_outbox,
)
from .saga import SagaRepository
from .schedule import ScheduleRepository, SchedulerPoller, ScheduleService
from .service_builder import ResiliantServiceBuilder
from .tracing import set_resilience_attributes
from .visibility import ResilienceVisibilityService

service_builder = "⛰️"

__all__: list[str] = [
    "ResiliantServiceBuilder",
    "ResiliantServiceFactory",
    "MessagingOutboxService",
    "OutboxDefinition",
    "OutboxRepository",
    "OutboxService",
    "TransactionOutboxService",
    "register_outbox",
    "DLQHandlerRegistry",
    "DLQRepository",
    "DLQRetryProcessor",
    "DLQService",
    "IdempotencyRepository",
    "IdempotencyService",
    "SagaRepository",
    "ScheduleRepository",
    "ScheduleService",
    "SchedulerPoller",
    "ResilienceVisibilityService",
    "set_resilience_attributes",
]
