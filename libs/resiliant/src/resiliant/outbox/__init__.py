"""Transactional outbox — a generic engine bound per use case to its own table.

* ``registry``     — :class:`OutboxDefinition` per outbox (messaging, transaction, …)
* ``outbox_service`` — writers (generic / messaging / transaction)
* ``outbox_repository`` — claiming, retries, stats for any outbox table
* ``dispatchers``  — delivery per :class:`~foundation.resiliant.outbox.OutboxTarget`
* ``outbox_poller`` — relay loop for one outbox table
* ``factory``      — entry point to build all of the above
"""

from .dispatchers import MessagingOutboxDispatcher, OutboxDispatchRouter
from .outbox_metrics import OutboxMetrics
from .outbox_poller import OutboxPoller, OutboxPollerState
from .outbox_repository import OutboxRepository
from .outbox_service import MessagingOutboxService, OutboxService, TransactionOutboxService
from .registry import OutboxDefinition, get_outbox_definition, outbox_definitions, register_outbox

__all__ = [
    "MessagingOutboxDispatcher",
    "MessagingOutboxService",
    "OutboxDefinition",
    "OutboxDispatchRouter",
    "OutboxMetrics",
    "OutboxPoller",
    "OutboxPollerState",
    "OutboxRepository",
    "OutboxService",
    "TransactionOutboxService",
    "get_outbox_definition",
    "outbox_definitions",
    "register_outbox",
]
