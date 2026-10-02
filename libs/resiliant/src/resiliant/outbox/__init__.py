"""Transactional outbox — a generic engine bound per use case to its own table.

* ``registry``     — :class:`OutboxDefinition` per outbox (messaging, transaction, …)
* ``outbox_service`` — writers (generic / messaging / transaction)
* ``outbox_repository`` — lock-based claim, outcomes, retention, stats for any outbox table
* ``dispatchers``  — delivery per :class:`~foundation.resiliant.outbox.OutboxTarget`
* ``outbox_processor`` — one relay step (claim → dispatch → outcome, one transaction, target circuit)
* ``outbox_poller`` — relay loop for one outbox table
* ``factory``      — entry point to build all of the above
"""

from .dispatchers import MessagingOutboxDispatcher, OutboxDispatchRouter
from .outbox_metrics import OutboxMetrics
from .outbox_poller import OutboxPoller
from .outbox_processor import OutboxProcessor, OutboxTargetCircuit
from .outbox_repository import OutboxFailure, OutboxRepository
from .outbox_service import MessagingOutboxService, OutboxService, TransactionOutboxService
from .registry import OutboxDefinition, get_outbox_definition, outbox_definitions, register_outbox

__all__ = [
    "MessagingOutboxDispatcher",
    "MessagingOutboxService",
    "OutboxDefinition",
    "OutboxDispatchRouter",
    "OutboxMetrics",
    "OutboxFailure",
    "OutboxPoller",
    "OutboxProcessor",
    "OutboxRepository",
    "OutboxTargetCircuit",
    "OutboxService",
    "TransactionOutboxService",
    "get_outbox_definition",
    "outbox_definitions",
    "register_outbox",
]
