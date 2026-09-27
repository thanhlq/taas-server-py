"""
Outbox registry — one :class:`OutboxDefinition` per use case.

The outbox engine (repository, service, poller, dispatch routing) is generic;
a definition binds it to a table model at runtime:

    OutboxDefinition(name='messaging', model=MessagingOutboxTable)

Built-ins: ``OutboxName.MESSAGING`` and ``OutboxName.TRANSACTION``. Apps add
their own with :func:`register_outbox` (a new ``OutboxRecordMixin`` table + one
line here or at startup) — no new repository / poller code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from foundation.resiliant.outbox import OutboxConfig, OutboxName, OutboxTarget

from resiliant.models.outbox import MessagingOutboxTable, OutboxRecordMixin, TransactionOutboxTable


@dataclass(frozen=True, slots=True)
class OutboxDefinition:
    """Binds the generic outbox engine to one use case."""

    name: str
    """Registry key, e.g. ``'messaging'`` (``OutboxName`` or an app-defined string)."""

    model: type[OutboxRecordMixin]
    """Table the records live in (an ``OutboxRecordMixin`` subclass)."""

    default_target: OutboxTarget = OutboxTarget.MESSAGING
    """Target stamped on new records unless the caller chooses another one."""

    config: OutboxConfig | None = field(default=None)
    """Per-outbox policy; ``None`` = the shared ``get_outbox_config()``."""

    description: str = ''


_REGISTRY: dict[str, OutboxDefinition] = {}


def register_outbox(definition: OutboxDefinition, *, replace: bool = False) -> OutboxDefinition:
    """Register (or with ``replace=True`` override) an outbox definition."""
    if definition.name in _REGISTRY and not replace:
        raise ValueError(f'Outbox "{definition.name}" is already registered')
    _REGISTRY[definition.name] = definition
    return definition


def get_outbox_definition(name: str) -> OutboxDefinition:
    """The definition registered under ``name`` (``KeyError`` with the known names otherwise)."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f'Unknown outbox "{name}"; registered: {sorted(_REGISTRY)}') from None


def outbox_definitions() -> list[OutboxDefinition]:
    """Every registered outbox, in registration order (the worker polls each)."""
    return list(_REGISTRY.values())


register_outbox(
    OutboxDefinition(
        name=OutboxName.MESSAGING,
        model=MessagingOutboxTable,
        description='Domain events published to the message broker.',
    )
)
register_outbox(
    OutboxDefinition(
        name=OutboxName.TRANSACTION,
        model=TransactionOutboxTable,
        description='Inbound transaction requests relayed to their target.',
    )
)
