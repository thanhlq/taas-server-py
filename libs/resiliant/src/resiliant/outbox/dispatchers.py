"""
Outbox dispatch — deliver a claimed record to its target.

* :class:`MessagingOutboxDispatcher` — ``OutboxTarget.MESSAGING``: publish to the broker.
* :class:`OutboxDispatchRouter`     — picks the dispatcher from ``record.target``.

A new target = one class implementing ``foundation.resiliant.outbox.IOutboxDispatcher``,
passed to the poller (``resiliant.outbox.factory.build_outbox_poller(dispatchers=…)``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from foundation.messaging.types import MessagingServiceT
from foundation.resiliant.outbox import (
    IOutboxDispatcher,
    IOutboxRecord,
    OutboxPublishError,
    OutboxTarget,
)
from foundation.state import get_service


class MessagingOutboxDispatcher:
    """Publishes ``record.payload`` to ``record.channel`` via ``MessagingServiceT``."""

    target = OutboxTarget.MESSAGING

    def __init__(self, publisher: MessagingServiceT | None = None) -> None:
        self._publisher = publisher

    @property
    def publisher(self) -> MessagingServiceT:
        """The broker publisher (resolved from the service registry on first use)."""
        if self._publisher is None:
            self._publisher = get_service(MessagingServiceT)
        return self._publisher

    async def dispatch(self, record: IOutboxRecord) -> None:
        if not record.channel:
            raise OutboxPublishError(f'{record.event_type} (id={record.id}) has no channel to publish to')
        await self.publisher.publish(
            channel=record.channel,
            message=record.payload,
            headers=record.headers,
            ordering_key=record.ordering_key,
        )


class OutboxDispatchRouter:
    """Routes each record to the dispatcher registered for ``record.target``."""

    def __init__(self, dispatchers: Iterable[IOutboxDispatcher]) -> None:
        self._dispatchers: Mapping[OutboxTarget, IOutboxDispatcher] = {d.target: d for d in dispatchers}

    @property
    def targets(self) -> list[OutboxTarget]:
        return list(self._dispatchers)

    async def dispatch(self, record: IOutboxRecord) -> None:
        dispatcher = self._dispatchers.get(record.target)
        if dispatcher is None:
            # Raising fails the record like any delivery error (retry → dead letter).
            raise OutboxPublishError(
                f'No dispatcher for target "{record.target}" (available: {[t.value for t in self._dispatchers]})'
            )
        await dispatcher.dispatch(record)


def default_dispatchers(publisher: Any = None) -> list[IOutboxDispatcher]:
    """Dispatchers for every built-in target."""
    return [MessagingOutboxDispatcher(publisher)]
