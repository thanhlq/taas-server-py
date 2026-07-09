"""
🎯 ``@messaging.subscriber`` Decorator

Faust-style decorator API built on top of
:class:`~core.messaging.faststream.faststream_aiokafka_impl.FastStreamKafkaMessagingService`.

Lets existing Faust agents migrate to FastStream with near-identical
call sites:

Before (Faust)::

    @faust_app.agent(get_topic(SharedTopics.SCOPE_TRACKER_EVENT))
    async def scope_tracker(stream):
        async for event in stream:
            message = faust.current_event().message
            await event_processor.process(
                event, headers=message.headers, topic=message.topic,
            )

After (FastStream)::

    from core.messaging.faststream.decorator import messaging
    from faststream.kafka import KafkaMessage

    @messaging.subscriber(SharedTopics.SCOPE_TRACKER_EVENT)
    async def scope_tracker(event: ScopeTrackerEvent, message: KafkaMessage):
        await event_processor.process(
            event, headers=message.headers, topic=message.topic,
        )

Implementation notes
--------------------
* Reuses the singleton ``FastStreamKafkaMessagingService`` instance so
  the registered subscriber participates in the same Kafka broker
  lifecycle (connect / start / stop) as the rest of the worker.
* Decodes the raw Kafka payload via the service's configured encoder
  (JSON / msgpack / Schema-Registry Avro) before invoking the user
  coroutine — handler code never sees raw bytes.
* On decode or handler errors, reports through ``report_error`` so the
  exception reaches the tracing manager and APM dashboards instead of
  crashing the subscriber task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Optional

from faststream.kafka import KafkaMessage
from platform_core.exceptions.report_error import report_error
from platform_core.messaging.types import IMessagingDecorators
from platform_core.messaging.utils.msg_encoder import MsgDecoderError
from platform_core.observability.log_factory import LogFactory

if TYPE_CHECKING:
    from .faststream_aiokafka_impl import FastStreamKafkaMessagingService


AgentHandler = Callable[..., Awaitable[None]]


class _MessagingDecorators(IMessagingDecorators):
    """Namespace exposing ``@messaging.subscriber`` and related decorators.

    The underlying ``FastStreamKafkaMessagingService`` is a singleton —
    resolving it lazily on first decorator application means modules
    using ``@messaging.subscriber`` can be imported before
    ``initialize_messaging_service()`` has been awaited.
    """

    def subscriber(
        self,
        topic: str,
        *,
        group_id: Optional[str] = None,
        auto_offset_reset: Optional[Literal['latest', 'earliest', 'none']] = None,
    ) -> Callable[[AgentHandler], AgentHandler]:
        """Register the decorated coroutine as a subscriber for *topic*.

        The decorated coroutine is invoked as ``handler(event, message)``
        for each incoming message, where:

        * ``event`` — the decoded ``BaseEvent`` subclass for the topic.
        * ``message`` — the FastStream :class:`~faststream.kafka.KafkaMessage`,
          exposing ``headers``, ``correlation_id``, the raw payload, etc.
          The Kafka topic name is also passed positionally for
          convenience because some ``KafkaMessage`` versions do not
          expose ``.topic`` directly.

        Args:
            topic: Kafka topic name to subscribe to.
            group_id: Override the consumer-group ID. Defaults to the
                service's configured group.
            auto_offset_reset: Override the offset-reset policy.

        Example::

            @messaging.agent(SharedTopics.SCOPE_TRACKER_EVENT)
            async def scope_tracker(event, message):
                await event_processor.process(
                    event, headers=message.headers, topic=message.topic,
                )
        """

        def wrap(func: AgentHandler) -> AgentHandler:
            service = _get_service()
            agent_name = getattr(func, '__name__', '<agent>')

            # NOTE: `msg: bytes` is REQUIRED. If typed `Any` (or anything other
            # than `bytes`), FastStream applies its built-in JSON/Pydantic
            # deserializer to the payload BEFORE calling this handler. That
            # breaks `schema-registry-avro` (Confluent wire format starts with
            # a 0x00 magic byte + 4-byte schema id) because JSON-parsing those
            # bytes raises and the message is dropped before we get a chance
            # to call `_decode_message` (which is the only path that knows
            # about the magic byte / sr_encoder).
            async def _agent_handler(msg: bytes, message: KafkaMessage) -> None:
                if not msg:
                    service.logger.warning(
                        f'Skipping null/empty message on topic={topic} '
                        f'agent={agent_name}'
                    )
                    return

                try:
                    event = await service._decode_message(topic, msg)  # type: ignore[reportPrivateUsage]
                except MsgDecoderError as exc:
                    report_error(
                        exc,
                        title='FastStream Agent Decode Error',
                        extra_context={
                            'topic': topic,
                            'agent': agent_name,
                        },
                        logger=service.logger,
                    )
                    return

                try:
                    await func(event, message)
                except Exception as exc:
                    report_error(
                        exc,
                        title='FastStream Agent Handler Error',
                        extra_context={
                            'topic': topic,
                            'agent': agent_name,
                        },
                        logger=service.logger,
                    )

            # resolved_group_id= group_id or f'{service.messaging_config.consumer_group_id}_agent_{agent_name}'
            resolved_group_id= group_id or service.messaging_config.consumer_group_id
            LogFactory().get_logger().debug(
                f'📨 RESOLVED group_id for agent={agent_name} on topic={topic}: {resolved_group_id}'
            )

            subscriber = service._broker.subscriber(  # type: ignore[reportPrivateUsage]
                topic,
                # Default to a per-handler consumer group so each
                # `@subscriber` registration is an independent logical
                # subscription (fan-out). Without this, multiple handlers
                # on the same topic share the service's main group, and
                # Kafka's partition-balancing inside that group means only
                # ONE handler ever sees a given record. Mirrors the
                # aiokafka backend's default of `{base}_agent_{name}`.
                group_id=resolved_group_id,
                auto_offset_reset=auto_offset_reset
                or service.subs_auto_offset_reset,
            )
            subscriber(func=_agent_handler)

            # NOTE: Do NOT pre-populate `service._main_subscribers[topic]`
            # or mutate `service.configured_topics` here. Under the new
            # per-agent group_id default the decorator subscriber lives in
            # a DIFFERENT consumer group than the main EventProcessor loop,
            # so there is no partition contention to avoid. Reserving the
            # topic would silently suppress the main-loop subscriber and
            # break EventProcessorFast (retry / DLQ / registry handlers)
            # for every decorated topic.

            service.logger.info(
                f'🤖 Registered agent: topic={topic} agent={agent_name}'
            )
            return func

        return wrap


def _get_service() -> 'FastStreamKafkaMessagingService':
    """Return the singleton ``FastStreamKafkaMessagingService`` instance.

    Imported lazily to avoid a circular import with the package
    ``__init__`` module.
    """
    from .faststream_aiokafka_impl import FastStreamKafkaMessagingService

    return FastStreamKafkaMessagingService()


messaging = _MessagingDecorators()
"""Singleton namespace for FastStream messaging decorators.

Usage::

    from core.messaging.faststream.decorator import messaging

    @messaging.subscriber(SharedTopics.SCOPE_TRACKER_EVENT)
    async def scope_tracker(event, message):
        ...
"""
