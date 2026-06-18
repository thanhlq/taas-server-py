"""
🎯 ``@messaging.subscriber`` Decorator (pure-aiokafka backend)

Faust-style decorator API built on top of
:class:`~messaging_kafka.aiokafka_messaging.AiokafkaMessagingService`.

Mirrors :mod:`messaging_faststream.decorator` but talks to ``aiokafka``
directly instead of going through FastStream.

Usage::

    from messaging_kafka.decorator import messaging

    @messaging.subscriber(SharedTopics.SCOPE_TRACKER_EVENT)
    async def scope_tracker(event: ScopeTrackerEvent, record):
        await event_processor.process(
            event, headers=dict(record.headers or []), topic=record.topic,
        )

    # No explicit `messaging.apply(service)` needed — the service drains
    # any pending subscriptions automatically inside ``start_consuming()``,
    # matching the FastStream backend's decorator UX.

Implementation notes
--------------------
* The plain :class:`AiokafkaMessagingService` has no synchronous
  subscriber-registration hook (unlike FastStream's ``_broker.subscriber``).
  Decoration only **records** the registration in an in-memory pending
  list. The subscribers are materialised when :meth:`apply` is awaited
  with a running service instance.
* Each ``@subscriber(topic)`` gets its own dedicated
  :class:`aiokafka.AIOKafkaConsumer` so the decorator handler is
  independent of the main consumption loop (no partition contention).
  By default a per-agent consumer group ``"{base}_agent_{name}"`` is used;
  callers can pass ``group_id=`` explicitly to override.
* Decoding goes through ``service._decode_message`` (same encoder /
  Schema-Registry path as the main loop). Decode / handler errors are
  routed through :func:`core.observability.error_reporter.report_error`.
* Subscription tasks are registered into ``service._subscriptions`` so
  the existing graceful-shutdown logic in ``AiokafkaMessagingService.astop``
  drains them.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional, TYPE_CHECKING, cast

from aiokafka import AIOKafkaConsumer, ConsumerRecord

from core.messaging.types import IMessagingDecorators, MessageHandler
from core.messaging.utils.msg_encoder import MsgDecoderError
from core.observability.error_reporter import report_error

if TYPE_CHECKING:
    from .aiokafka_messaging import AiokafkaMessagingService


AgentHandler = Callable[..., Awaitable[None]]


@dataclass
class _PendingSubscription:
    """A ``@subscriber`` invocation captured at decoration time."""

    topic: str
    handler: AgentHandler
    agent_name: str
    group_id: Optional[str] = None
    auto_offset_reset: Optional[Literal['latest', 'earliest', 'none']] = None


class _MessagingDecorators(IMessagingDecorators):
    """Namespace exposing ``@messaging.subscriber`` for the aiokafka backend.

    Decoration is sync and side-effect free beyond appending to
    :attr:`_pending`. :meth:`apply` performs the actual subscription
    against a running :class:`AiokafkaMessagingService`.
    """

    def __init__(self) -> None:
        self._pending: list[_PendingSubscription] = []
        # Track (topic, group_id) pairs already wired so re-running
        # ``apply`` does not spawn duplicate consumers in the same group.
        self._applied: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # IMessagingDecorators
    # ------------------------------------------------------------------

    def subscriber(
        self,
        topic: str,
        *,
        group_id: Optional[str] = None,
        auto_offset_reset: Optional[Literal['latest', 'earliest', 'none']] = None,
    ) -> Callable[[AgentHandler], AgentHandler]:
        """Register the decorated coroutine as a subscriber for *topic*.

        The decorated coroutine is invoked as ``handler(event, record)``
        for each message that arrives on *topic*, where:

        * ``event`` — the decoded :class:`~core.events.types.BaseEvent`.
        * ``record`` — the raw :class:`aiokafka.ConsumerRecord`, exposing
          ``headers``, ``key``, ``partition``, ``offset``, ``timestamp``,
          ``topic``, etc.

        Args:
            topic: Kafka topic name to subscribe to.
            group_id: Override the consumer-group id. Defaults to
                ``"{messaging_config.consumer_group_id}_agent_{name}"``
                to keep decorator subscribers isolated from the main
                consumption loop.
            auto_offset_reset: Override the offset-reset policy.
        """

        def wrap(func: AgentHandler) -> AgentHandler:
            agent_name = getattr(func, '__name__', '<agent>')
            self._pending.append(
                _PendingSubscription(
                    topic=topic,
                    handler=func,
                    agent_name=agent_name,
                    group_id=group_id,
                    auto_offset_reset=auto_offset_reset,
                )
            )
            return func

        return wrap

    # ------------------------------------------------------------------
    # Materialisation
    # ------------------------------------------------------------------

    async def apply(self, service: 'AiokafkaMessagingService') -> None:
        """Materialise all pending subscriptions against *service*.

        Must be called **after** ``service.start_producer()`` so the
        service is ``running``. Idempotent: subscriptions previously
        applied to *service* (same topic + group) are skipped.
        """
        if not getattr(service, 'running', False):
            raise RuntimeError(
                'AiokafkaMessagingService is not running; call '
                'start_producer() before messaging.apply(service).'
            )

        for pending in list(self._pending):
            await self._apply_one(service, pending)

    async def _apply_one(
        self,
        service: 'AiokafkaMessagingService',
        pending: _PendingSubscription,
    ) -> None:
        cfg = service.messaging_config
        group_id = (
            pending.group_id
            or f'{cfg.consumer_group_id}_agent_{pending.agent_name}'
        )

        dedupe_key = (pending.topic, group_id)
        if dedupe_key in self._applied:
            service.logger.debug(
                f'Skipping already-applied agent subscription: '
                f'topic={pending.topic} group_id={group_id}'
            )
            return

        auto_offset = pending.auto_offset_reset or cfg.kafka_auto_offset_reset

        # Build a dedicated consumer so we can hand the user coroutine
        # both the decoded event AND the raw ConsumerRecord — matching
        # the FastStream decorator's ``handler(event, message)`` shape.
        # Lazy import avoids a circular import with the service module.
        from .aiokafka_messaging import _SubscriptionInfo  # noqa: PLC0415  # type: ignore[reportPrivateUsage]

        consumer = AIOKafkaConsumer(
            pending.topic,
            bootstrap_servers=cfg.kafka_bootstrap_servers_list,
            group_id=group_id,
            auto_offset_reset=auto_offset,
            enable_auto_commit=True,
            **service._sasl_kwargs(),  # type: ignore[reportPrivateUsage]
        )
        await consumer.start()

        sub_id = str(uuid.uuid4())
        task = asyncio.create_task(
            self._consume_loop(service, consumer, pending, sub_id),
            name=f'agent::{pending.agent_name}',
        )

        service._subscriptions[sub_id] = _SubscriptionInfo(  # type: ignore[reportPrivateUsage]
            handler=cast(MessageHandler, pending.handler),
            topic=pending.topic,
            consumer_group=group_id,
            from_beginning=(auto_offset == 'earliest'),
            consumer=consumer,
            task=task,
        )
        service.stats.active_subscriptions = len(service._subscriptions)  # type: ignore[reportPrivateUsage]
        self._applied.add(dedupe_key)

        service.logger.info(
            f'🤖 Registered agent: topic={pending.topic} '
            f'agent={pending.agent_name} group_id={group_id}'
        )

    # ------------------------------------------------------------------
    # Per-subscription consume loop
    # ------------------------------------------------------------------

    @staticmethod
    async def _consume_loop(
        service: 'AiokafkaMessagingService',
        consumer: AIOKafkaConsumer,
        pending: _PendingSubscription,
        sub_id: str,
    ) -> None:
        topic = pending.topic
        handler = pending.handler
        agent_name = pending.agent_name

        try:
            service.logger.info(
                f'⬅️  Agent subscription started: sub_id={sub_id} '
                f'topic={topic} agent={agent_name}'
            )
            record: ConsumerRecord
            async for record in consumer:
                if not service.running:
                    break
                if record.value is None:
                    service.logger.warning(
                        f'Skipping null message on topic={topic} '
                        f'partition={record.partition} offset={record.offset}'
                    )
                    continue

                try:
                    event = await service._decode_message(topic, record.value)  # type: ignore[reportPrivateUsage]
                except MsgDecoderError as exc:
                    report_error(
                        exc,
                        title='Aiokafka Agent Decode Error',
                        extra_context={
                            'topic': topic,
                            'agent': agent_name,
                            'offset': record.offset,
                        },
                        logger=service.logger,
                    )
                    continue

                try:
                    await handler(event, record)
                except Exception as exc:
                    report_error(
                        exc,
                        title='Aiokafka Agent Handler Error',
                        extra_context={
                            'topic': topic,
                            'agent': agent_name,
                            'offset': record.offset,
                        },
                        logger=service.logger,
                    )
        except asyncio.CancelledError:
            service.logger.info(
                f'Agent subscription cancelled: sub_id={sub_id} topic={topic}'
            )
        except Exception as exc:
            report_error(
                exc,
                title='Aiokafka Agent Subscription Error',
                extra_context={'topic': topic, 'agent': agent_name},
                logger=service.logger,
            )
        finally:
            try:
                await consumer.stop()
            except Exception as exc:
                service.logger.warning(
                    f'Agent consumer stop failed: topic={topic} err={exc!r}'
                )


messaging = _MessagingDecorators()
"""Singleton namespace for aiokafka messaging decorators.

Usage::

    from messaging_kafka.decorator import messaging

    @messaging.subscriber(SharedTopics.SCOPE_TRACKER_EVENT)
    async def scope_tracker(event, record):
        ...

    # No explicit apply() needed — ``AiokafkaMessagingService.start_consuming()``
    # drains pending decorator subscriptions automatically.
"""
