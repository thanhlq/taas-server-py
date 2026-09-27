"""
Entry point for building outbox components (repository, service, poller) for any
registered outbox. ``ResiliantServiceFactory`` / ``ResiliantServiceBuilder`` delegate here.

    build_messaging_outbox_service()                       # domain events → broker
    build_transaction_outbox_service(OutboxTarget.MESSAGING)
    build_outbox_service('my_outbox')                      # app-registered outbox
    build_outbox_pollers(session_factory, publisher)       # one poller per outbox
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from foundation.messaging.types import MessagingServiceT
from foundation.resiliant.outbox import IOutboxDispatcher, OutboxConfig, OutboxName, OutboxTarget
from sqlalchemy.ext.asyncio import AsyncSession

from .dispatchers import default_dispatchers
from .outbox_poller import OutboxPoller
from .outbox_repository import OutboxRepository
from .outbox_service import MessagingOutboxService, OutboxService, TransactionOutboxService
from .outbox_settings import get_outbox_config
from .registry import OutboxDefinition, get_outbox_definition, outbox_definitions

# Typed service per built-in outbox; app-registered outboxes get the generic one.
_SERVICE_CLASSES: dict[str, type[OutboxService]] = {
    OutboxName.MESSAGING: MessagingOutboxService,
    OutboxName.TRANSACTION: TransactionOutboxService,
}


def _definition(outbox: str | OutboxDefinition) -> OutboxDefinition:
    return outbox if isinstance(outbox, OutboxDefinition) else get_outbox_definition(outbox)


def _config(definition: OutboxDefinition, config: OutboxConfig | None) -> OutboxConfig:
    return config or definition.config or get_outbox_config()


def build_outbox_repository(
    outbox: str | OutboxDefinition = OutboxName.MESSAGING, config: OutboxConfig | None = None
) -> OutboxRepository:
    """Repository bound to the table of ``outbox``."""
    definition = _definition(outbox)
    return OutboxRepository(definition.model, _config(definition, config))


def build_outbox_service(
    outbox: str | OutboxDefinition = OutboxName.MESSAGING,
    target: OutboxTarget | None = None,
    config: OutboxConfig | None = None,
) -> OutboxService:
    """Service writing to ``outbox``; new records default to ``target``
    (else the outbox's ``default_target``)."""
    definition = _definition(outbox)
    resolved = _config(definition, config)
    service_class = _SERVICE_CLASSES.get(definition.name, OutboxService)
    return service_class(
        definition,
        resolved,
        target=target,
        repository=OutboxRepository(definition.model, resolved),
    )


def build_messaging_outbox_service(config: OutboxConfig | None = None) -> MessagingOutboxService:
    """The messaging outbox (``IOutboxService``)."""
    return build_outbox_service(OutboxName.MESSAGING, OutboxTarget.MESSAGING, config)  # type: ignore[return-value]


def build_transaction_outbox_service(
    target: OutboxTarget = OutboxTarget.MESSAGING, config: OutboxConfig | None = None
) -> TransactionOutboxService:
    """The transaction outbox (``ITransactionOutboxService``) relaying to ``target``."""
    return build_outbox_service(OutboxName.TRANSACTION, target, config)  # type: ignore[return-value]


def build_outbox_poller(
    session_factory: Callable[[], AsyncSession],
    outbox: str | OutboxDefinition = OutboxName.MESSAGING,
    publisher: MessagingServiceT | None = None,
    dispatchers: list[IOutboxDispatcher] | None = None,
    config: OutboxConfig | None = None,
) -> OutboxPoller:
    """Pure poller for one outbox table (the worker drives ``run()`` / ``stop()``)."""
    definition = _definition(outbox)
    resolved = _config(definition, config)
    return OutboxPoller(
        config=resolved,
        session_factory=session_factory,
        repository=OutboxRepository(definition.model, resolved),
        dispatchers=dispatchers or default_dispatchers(publisher),
        name=definition.name,
    )


def build_outbox_pollers(
    session_factory: Callable[[], AsyncSession],
    publisher: MessagingServiceT | None = None,
    outboxes: Iterable[str] | None = None,
    dispatchers: list[IOutboxDispatcher] | None = None,
) -> list[OutboxPoller]:
    """One poller per outbox — every registered outbox unless ``outboxes`` narrows it."""
    names = list(outboxes) if outboxes is not None else [d.name for d in outbox_definitions()]
    return [build_outbox_poller(session_factory, name, publisher, dispatchers) for name in names]
