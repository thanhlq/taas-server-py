"""
🎯 Generic flow-driven handler & schema registration.

Domain modules (``iam``, ``business``, ``billing``, …) declare their event
flows as a ``Mapping[str, Iterable[EventStep]]`` (see
``core.iam.events.iam_event_flows.ALL_FLOWS`` for the canonical example).
This module turns those flow definitions into:

* runtime handler registrations on a ``HandlerRegistry``, and
* Avro schema registrations on an ``IMessagingService``,

so adding a new step in a domain's flow file is the only change required
to wire a new handler / event / schema.

A domain hooks in by providing two things:

1. ``flows`` — its ``ALL_FLOWS`` mapping.
2. ``topic_for_event`` — a callable that resolves an event class to its
   Kafka topic (or returns ``None`` if the event is not routable here).
   This is the only domain-specific knowledge these functions need.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

import msgspec

from ..types import BaseEvent, MessagingServiceT
from .event_handler import EventStep, HandlerRegistry, handlerRegistry

if TYPE_CHECKING:
    from foundation.app.types import ApiApplicationModuleT


logger = logging.getLogger(__name__)

FlowMap = Mapping[str, Iterable[EventStep]]
"""``{flow_name: (EventStep, EventStep, …)}`` — the shape of a domain's
``ALL_FLOWS``."""

# TopicForEvent = Callable[[type[BaseEvent]], str | None]
TopicForEvent = Callable[[type[BaseEvent]], str]
"""Resolve an event class to its Kafka topic, or ``None`` if not routable."""


_NO_DEFAULT = object()
"""Sentinel meaning 'no default found' — so a real ``None`` default is preserved."""


def _field_default(cls: type, field_name: str) -> Any:
    """Return the default declared for ``field_name`` on ``cls``.

    Works across whichever model library an event class is built with — msgspec
    ``Struct`` (the current default), ``dataclasses.dataclass`` and Pydantic
    ``BaseModel`` (v2/v1) — and falls back to a plain class attribute. Returns
    :data:`_NO_DEFAULT` when no default can be resolved.
    """
    # msgspec.Struct — defaults live in struct metadata, not as class attrs.
    if issubclass(cls, msgspec.Struct):
        for f in msgspec.structs.fields(cls):
            if f.name == field_name:
                if f.default is not msgspec.NODEFAULT:
                    return f.default
                if f.default_factory is not msgspec.NODEFAULT:
                    return f.default_factory()
        return _NO_DEFAULT

    # dataclass — ``__dataclass_fields__`` carries default / default_factory.
    dc_fields = getattr(cls, '__dataclass_fields__', None)
    if isinstance(dc_fields, dict) and field_name in dc_fields:
        f = dc_fields[field_name]
        if f.default is not dataclasses.MISSING:
            return f.default
        if f.default_factory is not dataclasses.MISSING:
            return f.default_factory()
        return _NO_DEFAULT

    # Pydantic v2 — ``model_fields[name]`` is a FieldInfo.
    model_fields = getattr(cls, 'model_fields', None)
    if isinstance(model_fields, dict) and field_name in model_fields:
        info = model_fields[field_name]
        factory = getattr(info, 'default_factory', None)
        if callable(factory):
            return factory()
        is_required = getattr(info, 'is_required', None)
        if callable(is_required) and is_required():
            return _NO_DEFAULT
        return getattr(info, 'default', _NO_DEFAULT)

    # Pydantic v1 — ``__fields__[name]`` is a ModelField.
    v1_fields = getattr(cls, '__fields__', None)
    if isinstance(v1_fields, dict) and field_name in v1_fields:
        info = v1_fields[field_name]
        factory = getattr(info, 'default_factory', None)
        if callable(factory):
            return factory()
        return getattr(info, 'default', _NO_DEFAULT)

    # Fallback: a plain class attribute (covers plain classes, and dataclasses
    # that expose the default as a class attribute).
    return getattr(cls, field_name, _NO_DEFAULT)


def event_type_value(event_cls: type[BaseEvent]) -> str:
    """Return the ``event_type`` enum-value declared on an event class.

    Every event declares ``event_type`` with a default enum value
    (``event_type: str = field(default=SomeEnum.XXX)``); we read that default
    rather than instantiating the event (which may require domain fields).

    The event class may be built with any supported model library — msgspec
    ``Struct`` (the current default), a dataclass, or a Pydantic model — so the
    default is resolved via :func:`_field_default` rather than assuming one.
    """
    default = _field_default(event_cls, 'event_type')
    if default is _NO_DEFAULT:
        raise TypeError(
            f"{event_cls.__name__} does not declare a default for 'event_type'; "
            'cannot resolve its event type without instantiating it.'
        )
    return cast(str, default)


def iter_flow_steps(flows: FlowMap) -> Iterable[EventStep]:
    """Yield every ``EventStep`` from every flow in ``flows``."""
    for steps in flows.values():
        yield from steps


def iter_flow_event_classes(flows: FlowMap) -> Iterable[type[BaseEvent]]:
    """Yield every event class referenced by ``flows``, de-duplicated."""
    seen: set[type[BaseEvent]] = set()
    for step in iter_flow_steps(flows):
        for event_cls in (step.event, *step.emits):
            if event_cls not in seen:
                seen.add(event_cls)
                yield event_cls


def topic_event_schema_pairs(
    flows: FlowMap,
    topic_for_event: TopicForEvent,
) -> list[tuple[str, type[BaseEvent]]]:
    """Return every ``(topic, event class)`` pair that needs a schema.

    One entry per *event class*, not per topic. Topics routinely carry several
    event types (7 map to ``iam.user.registered``, 9 to ``iam.auth``), and they
    are siblings rather than a subclass chain — so no single schema can stand in
    for the rest. Each class is registered under its own subject, following
    Confluent's TopicRecordNameStrategy.
    """
    pairs: list[tuple[str, type[BaseEvent]]] = []
    for event_cls in iter_flow_event_classes(flows):
        topic = topic_for_event(event_cls)
        if topic is None:  # type: ignore[unreachable]  # mypy doesn't know TopicForEvent is non-None
            raise ValueError(
                f"Event class {event_cls.__name__} is not routable: "
                "topic_for_event returned None. All events in flows must be routable."
            )
        pairs.append((topic, event_cls))
    return pairs


def topic_to_schema_event(
    flows: FlowMap,
    topic_for_event: TopicForEvent,
) -> dict[str, type[BaseEvent]]:
    """Map ``topic → one event class``.

    .. deprecated::
        Retained for callers that only need a representative class per topic.
        Registration must use :func:`topic_event_schema_pairs` instead — keeping
        one schema per topic silently drops the fields that sibling event types
        on the same topic do not share.
    """
    by_topic: dict[str, type[BaseEvent]] = {}
    for topic, event_cls in topic_event_schema_pairs(flows, topic_for_event):
        current = by_topic.get(topic)
        if current is None or issubclass(current, event_cls):
            by_topic[topic] = event_cls
    return by_topic


def register_schema_registry_schemas(
    msg_service: MessagingServiceT,
    *,
    flows: FlowMap,
    topic_for_event: TopicForEvent,
) -> None:
    """Register Avro schemas for every event class referenced by ``flows``."""
    for topic, event_cls in topic_event_schema_pairs(flows, topic_for_event):
        msg_service.register_schema(topic, event_cls)

def register_event_handlers_for_app_module(*, app: ApiApplicationModuleT, msg_service: MessagingServiceT) -> None:
    """Register handlers for an application module's flows.

    This is a convenience wrapper around :func:`register_handlers_from_flows`
    that reads the flows and topic resolver from an ``ApiApplicationModuleT``
    instance.
    """
    register_handlers_from_flows(
        flows=app.get_event_flows(),
        msg_service=msg_service,
        topic_for_event=app.get_topic_for_event,
    )

    register_schema_registry_schemas(
        msg_service,
        flows=app.get_event_flows(),
        topic_for_event=app.get_topic_for_event,
    )

def register_handlers_from_flows(
    *,
    flows: FlowMap,
    msg_service: MessagingServiceT,
    topic_for_event: TopicForEvent,
    registry: HandlerRegistry = handlerRegistry,
    domain_label: str = 'event',
) -> None:
    """Register handlers from ``flows`` into ``registry``.

    For each ``EventStep`` in every flow, every handler class is instantiated
    once and bound to ``step.event``'s ``event_type``. Duplicate
    (event_type, handler_cls) pairs across flows are ignored.

    Schema-registry registration runs first as a side effect — both
    registrations are derived from the same flow definitions, so callers
    only need to invoke this function.

    Args:
        flows: The domain's ``ALL_FLOWS`` mapping.
        msg_service: Messaging service used for schema registration.
        topic_for_event: Resolves an event class to its Kafka topic.
        registry: Handler registry to populate. Defaults to the global one.
        domain_label: Human-readable label used in disable-warning logs.
    """
    if not msg_service.is_consumer_enabled():
        logger.info(
            f'🎯 ⚠️ Kafka consumer is disabled. {domain_label} event handlers '
            f'will not be registered.'
        )
        return

    register_schema_registry_schemas(
        msg_service,
        flows=flows,
        topic_for_event=topic_for_event,
    )

    # Register all the event classes in the flow definition for event deserialization/reconstruction of event class
    _registered_handlers: set[tuple[str, type]] = set()
    _registered_events: set[type[BaseEvent]] = set()

    for step in iter_flow_steps(flows):
        event_type = event_type_value(step.event)
        if step.event not in _registered_events:
            msg_service.register_event_serializer(step.event)
            _registered_events.add(step.event)
        for emitted in step.emits:
            if emitted not in _registered_events:
                msg_service.register_event_serializer(emitted)
                _registered_events.add(emitted)

        for handler_cls in step.handlers:
            if (event_type, handler_cls) in _registered_handlers:
                continue
            _registered_handlers.add((event_type, handler_cls))
            registry.register(event_type, handler_cls())
