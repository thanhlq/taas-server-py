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

from collections.abc import Callable, Iterable, Mapping
from typing import cast

from core.conf import get_app_settings
from core.events.event_handler import EventStep, HandlerRegistry, handlerRegistry
from core.events.types import BaseEvent
from core.messaging.types import IMessagingService, MessageEncodingType

FlowMap = Mapping[str, Iterable[EventStep]]
"""``{flow_name: (EventStep, EventStep, …)}`` — the shape of a domain's
``ALL_FLOWS``."""

TopicForEvent = Callable[[type[BaseEvent]], str | None]
"""Resolve an event class to its Kafka topic, or ``None`` if not routable."""


def event_type_value(event_cls: type[BaseEvent]) -> str:
    """Return the ``event_type`` enum-value declared on a BaseEvent dataclass.

    Every event sets ``event_type: str = field(default=SomeEnum.XXX)``;
    we read that default rather than instantiating the event (which may
    require domain fields).
    """
    return cast(str, event_cls.__dataclass_fields__['event_type'].default)


def iter_flow_steps(flows: FlowMap) -> Iterable[EventStep]:
    """Yield every ``EventStep`` from every flow in ``flows``."""
    for steps in flows.values():
        yield from steps


def topic_to_schema_event(
    flows: FlowMap,
    topic_for_event: TopicForEvent,
) -> dict[str, type[BaseEvent]]:
    """Map ``topic → event class`` to register with the schema registry.

    Multiple event classes may map to the same topic (e.g. both
    ``UserDirectoryCreatedEvent`` and ``UserRegisteredEvent`` use
    ``iam.user.registered``). We register **one** schema per topic, picking
    the most-general (least-derived) event class so subclasses remain
    wire-compatible.
    """
    by_topic: dict[str, type[BaseEvent]] = {}
    candidates: list[type[BaseEvent]] = []
    for step in iter_flow_steps(flows):
        candidates.append(step.event)
        candidates.extend(step.emits)

    for event_cls in candidates:
        topic = topic_for_event(event_cls)
        if topic is None:
            continue
        current = by_topic.get(topic)
        if current is None or issubclass(current, event_cls):
            by_topic[topic] = event_cls
    return by_topic


def register_schema_registry_schemas(
    msg_service: IMessagingService,
    *,
    flows: FlowMap,
    topic_for_event: TopicForEvent,
) -> None:
    """Register Avro schemas for every topic referenced by ``flows``."""
    if get_app_settings().MESSAGE_ENCODING != MessageEncodingType.SCHEMA_REGISTRY_AVRO:
        return

    for topic, event_cls in topic_to_schema_event(flows, topic_for_event).items():
        msg_service.register_schema(topic, event_cls.avro_schema_to_python())


def register_handlers_from_flows(
    *,
    flows: FlowMap,
    msg_service: IMessagingService,
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
    if not get_app_settings().KAFKA_CONSUMER_ENABLE:
        print(
            f'⚠️ Kafka consumer is disabled. {domain_label} event handlers '
            f'will not be registered.'
        )
        return

    register_schema_registry_schemas(
        msg_service, flows=flows, topic_for_event=topic_for_event,
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
