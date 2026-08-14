"""
🚀 Pure-aiokafka implementation of :class:`IMessagingPubSubService`.

This mirrors :class:`messaging_faststream.faststream_aiokafka_impl.FastStreamKafkaMessagingService`
but uses the plain ``aiokafka`` library directly, without the FastStream
abstraction layer. Configuration is read exclusively from
:attr:`BaseMessagingService.messaging_config` (a frozen
:class:`BaseMessagingConfig` snapshot built once in ``BaseMessagingService.__init__``).

Architecture
------------

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │              AiokafkaMessagingService                   │
    │                                                         │
    │  ┌───────────────┐  ┌─────────────────────────────────┐ │
    │  │ AIOKafkaProd. │  │  Dynamic subscriptions          │ │
    │  │ AIOKafkaCons. │  │  sub_id → {consumer, task}      │ │
    │  │ DLQ producer  │  │  Each gets its own consumer +   │ │
    │  │ Admin client  │  │  unique consumer group          │ │
    │  └───────────────┘  └─────────────────────────────────┘ │
    │                                                         │
    │  Main loop (start_consuming):                           │
    │      AIOKafkaConsumer(*CONSUMER_CHANNELS)                    │
    │        → _process_message() → EventProcessorFast        │
    │            → handler / retry / DLQ                      │
    │                                                         │
    │  Optional: SchemaRegistryEncoder (Avro)                 │
    └─────────────────────────────────────────────────────────┘

Lifecycle
---------

.. code-block:: python

    service = AiokafkaMessagingService()

    # API / producer-only
    await service.start_producer()
    await service.publish("iam.user.registered", event)

    # Worker / consumer
    await service.start_producer()
    await service.start_consumer()
    await service.start_consuming()           # blocks (concurrent)
    # or
    await service.start_consuming_sequential() # blocks (one-at-a-time)
"""

from __future__ import annotations

import asyncio
import ssl
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from aiokafka.structs import RecordMetadata
from foundation.exceptions.report_error import report_error
from foundation.messaging.events.event_processor import EventProcessor
from foundation.messaging.kafka.base_kafka_messaging import BaseKafkaMessagingService
from foundation.messaging.types import (
    BaseEvent,
    BaseSendableMessage,
    DlqEvent,
    MessageHandler,
    MessageServiceStats,
    MessagingProvider,
    MessagingServiceT,
)
from foundation.messaging.utils.msg_encoder import MsgDecoderError
from foundation.observability.tracing_factory import TracingFactory
from foundation.observability.types import ITracingManager
from foundation.resiliant.retry import retry
from foundation.utils.singleton import singleton

from messaging_kafka.aiokafka_security import get_aiokafka_security_kwargs
from messaging_kafka.kafka_admin_service import KafkaAdminService

from .aiokafka_helper import AiokafkaHelper

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _SubscriptionInfo:
    """Bookkeeping for a single ``subscribe()`` call."""

    handler: MessageHandler
    topic: str
    consumer_group: str
    from_beginning: bool
    consumer: AIOKafkaConsumer = field(repr=False)
    task: asyncio.Task = field(repr=False)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

@singleton
class AiokafkaMessagingService(BaseKafkaMessagingService[AIOKafkaProducer, AIOKafkaConsumer, RecordMetadata], MessagingServiceT[AIOKafkaProducer, AIOKafkaConsumer, RecordMetadata]):
    """
    Kafka pub/sub service using pure ``aiokafka``.

    Inherits configuration handling (``self.messaging_config``), encoder
    management, DLQ helpers, and schema-registry plumbing from
    :class:`BaseMessagingService`.
    """

    _admin_client: Optional[KafkaAdminService] = None

    def __init__(self, *, avro_schemas: Optional[dict[str, dict]] = None) -> None:
        super().__init__(avro_schemas=avro_schemas)

        self.dlq_producer: Optional[AIOKafkaProducer] = None
        self.admin_client: Optional[AIOKafkaAdminClient] = None

        # Built once on first use, shared by producer/consumer/admin clients.
        self._cached_ssl_context: Optional[ssl.SSLContext] = None

        # Dynamic subscriptions (created via ``subscribe()``).
        self._subscriptions: dict[str, _SubscriptionInfo] = {}

        # Bounded set of in-flight ``_process_message`` tasks for the main loop.
        self.processing_tasks: set[asyncio.Task[Any]] = set()

        self.running: bool = False
        self.event_processor = EventProcessor(stats=self.stats)

        self.logger.info(
            f'📨 🔌  AiokafkaMessagingService initialised, '
            f'encoder={self.msg_encoder}, '
            f'bootstrap={self.kafka_config.KAFKA_BOOTSTRAP_SERVERS}, '
        )

    # -----------------------------------------------------------------------
    # IMessagingService — introspection
    # -----------------------------------------------------------------------

    def get_provider(self) -> MessagingProvider:
        return MessagingProvider.KAFKA_AIOKAFKA

    def get_stats(self) -> MessageServiceStats:
        """Return a snapshot of current service statistics."""
        self.stats.running = self.running
        self.stats.active_tasks = len(self.processing_tasks)
        self.stats.active_subscriptions = len(self._subscriptions)
        return self.stats

    async def get_admin_client(self) -> KafkaAdminService:
        """ Lazily create and return the KafkaAdminService singleton. """
        if self._admin_client is None:
            self._admin_client = KafkaAdminService(
                config=self.config,
                kafka_config=self.kafka_config,
                kafka_security_config=self.security_config,
            )
            await self._admin_client.start()

        return self._admin_client

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    @retry.decorator(name='start_kafka_producer')
    async def start_producer(self) -> None:
        """Create and start the producer, DLQ producer, and admin client."""
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.kafka_bootstrap_servers,
                **get_aiokafka_security_kwargs(self.security_config),
            )
            await self.producer.start()

            if self.dlq_enabled:
                self.dlq_producer = AIOKafkaProducer(
                    bootstrap_servers=self.kafka_bootstrap_servers,
                    **get_aiokafka_security_kwargs(self.security_config),
                )
                await self.dlq_producer.start()

            self.running = True
            self.logger.info('📨 ➡️  Kafka producer + admin client ready')

        except Exception as exc:
            report_error(
                exc,
                title=f'📬 Kafka Producer Start Error (url: {self.kafka_bootstrap_servers})',
                logger=self.logger,
            )
            raise

    def create_consumer(self, **kwargs) -> AIOKafkaConsumer:
        return AIOKafkaConsumer(
            *self.consumer_channels,
            bootstrap_servers=self.kafka_bootstrap_servers,
            group_id=self.get_consumer_group_id(),
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=self.auto_commit,
            max_poll_records=self.kafka_config.KAFKA_MAX_POLL_RECORDS,
            session_timeout_ms=self.kafka_config.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self.kafka_config.KAFKA_HEARTBEAT_INTERVAL_MS,
            **get_aiokafka_security_kwargs(self.security_config),
            **kwargs,
        )

    async def start_consumer(self) -> None:
        """Create and start the main-loop consumer for the configured topics."""
        if not self.producer:
            raise RuntimeError('Call start_producer() before start_consumer().')

        try:
            self.consumer: AIOKafkaConsumer = self.create_consumer()
            await self.consumer.start()
            self.logger.info(
                f'⬅️  Kafka consumer started: topics={self.consumer_channels} '
                f'group_id={self.get_consumer_group_id()}'
            )
        except Exception as exc:
            report_error(exc, title='Kafka Consumer Start Error', logger=self.logger)
            raise

    async def stop(self) -> None:
        """Gracefully shut down all clients and drain in-flight tasks."""
        try:
            await self._do_stop()
            self.logger.info('📨 👋 Kafka service stopped successfully')
        except Exception as exc:
            report_error(exc, title='Kafka Service Stop Error', logger=self.logger)

    async def _do_stop(self) -> None:
        self.logger.info('Stopping Kafka service …')
        self.running = False

        # Cancel dynamic subscription tasks.
        for sub_info in list(self._subscriptions.values()):
            if not sub_info.task.done():
                sub_info.task.cancel()

        # Cancel and wait for in-flight processing tasks.
        if self.processing_tasks:
            self.logger.info(
                f'Cancelling {len(self.processing_tasks)} in-flight processing tasks',
            )
            for task in self.processing_tasks:
                if not task.done():
                    task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.processing_tasks, return_exceptions=True),
                    timeout=self.kafka_config.KAFKA_GRACEFUL_SHUTDOWN_TIMEOUT,
                )
            except TimeoutError:
                self.logger.warning('Graceful shutdown timeout exceeded')

        # Drain EventProcessor.
        if self.event_processor:
            try:
                await asyncio.wait_for(
                    self.event_processor.cleanup(),
                    timeout=self.kafka_config.KAFKA_GRACEFUL_SHUTDOWN_TIMEOUT,
                )
            except TimeoutError:
                self.logger.warning('EventProcessor cleanup timeout exceeded')
            except Exception as exc:
                report_error(
                    exc, title='EventProcessor Cleanup Error', logger=self.logger
                )

        # Stop clients with a per-client timeout to avoid hangs.
        client_timeout = 5.0
        if self.consumer:
            await self._safe_stop(self.consumer.stop(), client_timeout, 'Consumer')
        if self.producer:
            await self._safe_stop(self.producer.stop(), client_timeout, 'Producer')
        if self.dlq_producer:
            await self._safe_stop(
                self.dlq_producer.stop(), client_timeout, 'DLQ producer'
            )
        if self.admin_client:
            await self._safe_stop(
                self.admin_client.close(), client_timeout, 'Admin client'
            )

        self.logger.info(f'Kafka service stopped | stats={self.stats}')

    async def _safe_stop(self, coro: Any, timeout: float, label: str) -> None:
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except (TimeoutError, Exception) as exc:
            self.logger.warning(f'{label} stop timed out or failed: {exc!r}')

    # -----------------------------------------------------------------------
    # Main consumption loop
    # -----------------------------------------------------------------------

    async def start_consuming(self) -> None:
        """Blocking concurrent consumption loop bounded by ``max_concurrent_tasks``."""
        await self._run_consuming(max_workers=self.kafka_config.KAFKA_CONSUMER_MAX_WORKERS)

    async def start_consuming_sequential(self) -> None:
        """Blocking sequential consumption loop (preserves ordering)."""
        await self._run_consuming(max_workers=1)

    async def _run_consuming(self, max_workers: int) -> None:
        if not self.consumer:
            raise RuntimeError('Consumer not initialised. Call start_consumer() first.')

        # Auto-materialise any @messaging.subscriber(...) registrations that
        # were collected before consumption started. This mirrors how the
        # FastStream backend buffers subscribers on its broker and starts
        # them as part of broker.start() — callers never have to invoke
        # `messaging.apply(service)` explicitly, keeping the two backends'
        # decorator APIs symmetric. Safe to call repeatedly: `apply()` dedupes
        # against an internal `_applied` set keyed by (topic, group_id).
        # Imported lazily to avoid a circular import with the decorator module.
        from .decorator import messaging as _decorator_messaging  # noqa: PLC0415
        await _decorator_messaging.apply(self)

        self.logger.info(
            f'🔄 Starting Kafka consumption loop | max_workers={max_workers} '
            f'topics={self.consumer_channels}'
        )

        try:
            async for message in self.consumer:
                if not self.running:
                    break

                if max_workers <= 1:
                    await self._process_message(message)
                    continue

                # Throttle: wait until we drop below the concurrency cap.
                while len(self.processing_tasks) >= max_workers:
                    done, pending = await asyncio.wait(
                        self.processing_tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    self.processing_tasks = pending
                    for t in done:
                        exc = t.exception()
                        if isinstance(exc, Exception):
                            report_error(
                                exc,
                                title='Task Processing Error',
                                logger=self.logger,
                            )

                task = asyncio.create_task(self._process_message(message))
                self.processing_tasks.add(task)
                task.add_done_callback(self.processing_tasks.discard)

        except asyncio.CancelledError:
            self.logger.info('Consumption loop cancelled')
        except Exception as exc:
            report_error(exc, title='Error in consumption loop', logger=self.logger)
            raise

    async def _process_message(self, message: ConsumerRecord) -> None:
        """Decode, dispatch, retry, DLQ, and commit a single Kafka message."""
        traceparent = AiokafkaHelper.find_traceparent(message)

        if message.value is None:
            self.logger.warning(
                f'Skipping null message: topic={message.topic} '
                f'partition={message.partition} offset={message.offset}'
            )
            return

        try:
            event = await self._decode_message(message.topic, message.value)
        except MsgDecoderError as exc:
            report_error(
                exc,
                title='Kafka Message Decode Error',
                extra_context={'topic': message.topic, 'offset': message.offset},
                logger=self.logger,
            )
            self.stats.messages_failed += 1
            await self._maybe_commit()
            return

        self.logger.debug(
            f'🔀 Processing: topic={message.topic} partition={message.partition} '
            f'offset={message.offset} event_id={event.event_id} '
            f'event_type={event.event_type}'
        )

        try:
            result = await self.event_processor.process_event(event, traceparent)
        except Exception as exc:
            report_error(
                exc,
                title='Unexpected Kafka Message Processing Error',
                extra_context={'topic': message.topic, 'offset': message.offset},
                logger=self.logger,
            )
            self.stats.messages_failed += 1
            await self._maybe_commit()
            return

        if result.success:
            self.stats.messages_processed += 1
            self.logger.debug(
                f'⬅️  Processed: event_id={event.event_id} '
                f'event_type={event.event_type} '
                f'processing_time_ms={result.processing_time_ms}'
            )
            await self._maybe_commit()
            return

        # Failure path.
        self.stats.messages_failed += 1
        if (
            self.dlq_enabled
            and event.retry_count >= self.config.RETRY_MAX_RETRIES
        ):
            # event.handler_name = result.handler_name
            await self.send_to_dlq(event, result.error, traceparent)
            self.stats.messages_dlq += 1
            await self._maybe_commit()
        elif self.dlq_enabled:
            self.stats.messages_retried += 1
        else:
            self.logger.warning(
                f'⬅️  Processing failed and DLQ disabled: event_id={event.event_id} '
                f'event_type={event.event_type} error={result.error!r}'
            )

    async def _maybe_commit(self) -> None:
        """Commit consumer offset when auto-commit is disabled."""
        if self.consumer and not self.auto_commit:
            try:
                await self.consumer.commit()
            except Exception as exc:
                self.logger.warning(f'Consumer offset commit failed: {exc!r}')

    # -----------------------------------------------------------------------
    # IMessagingService — publish
    # -----------------------------------------------------------------------

    async def publish(
        self,
        channel: str,
        message: BaseSendableMessage | dict,
        *,
        key: bytes | str | Any | None = None,
        timestamp_ms: int | None = None,
        headers: dict[str, str] | None = None,
        partition: Optional[int] = None,
        correlation_id: str | None = None,
        reply_to: str = '',
        no_confirm: bool = False,
        **kwargs: Any,
    ) -> asyncio.Future[RecordMetadata | None] | None:
        """
        Publish *message* to Kafka topic *channel*.

        Encodes the event (JSON / msgpack / Avro via Schema Registry),
        injects W3C trace headers, and sends via ``AIOKafkaProducer``.
        """
        if not self.producer:
            raise RuntimeError('Producer not initialised. Call start_producer() first.')

        if correlation_id is None and headers is not None:
            correlation_id = headers.get('correlation_id')

        try:
            _msg_any: Any = message
            event_id = getattr(message, 'event_id', None) or (
                _msg_any.get('event_id') if isinstance(message, dict) else None
            )
            event_type = getattr(message, 'event_type', None) or (
                _msg_any.get('event_type') if isinstance(message, dict) else None
            )

            self.logger.debug(
                f'➡️  Publishing: channel={channel} event_id={event_id} '
                f'event_type={event_type} correlation_id={correlation_id}'
            )

            encoded = await self._encode_message(channel, message)

            # Build headers: prefer caller-provided, else propagate active trace.
            kafka_headers: list[tuple[str, bytes]]
            if headers:
                kafka_headers = AiokafkaHelper.to_aiokafka_headers(headers)
            else:
                tracing_mgr: Optional[ITracingManager] = (
                    TracingFactory().get_tracing_manager()
                )
                kafka_headers = (
                    tracing_mgr.get_propagated_aiokafka_headers()
                    if tracing_mgr is not None
                    else []
                )

            key_bytes: bytes | None = None
            if isinstance(key, str):
                key_bytes = key.encode('utf-8')
            elif isinstance(key, bytes):
                key_bytes = key

            send_kwargs: dict[str, Any] = {
                'value': encoded,
                'headers': kafka_headers,
            }
            if key_bytes is not None:
                send_kwargs['key'] = key_bytes
            if partition is not None:
                send_kwargs['partition'] = partition
            if timestamp_ms is not None:
                send_kwargs['timestamp_ms'] = timestamp_ms

            # Do we need to update the kafka header if the encoded message is bytes? If the message is bytes, it means it has already been encoded (e.g. Avro binary) and we should set the content-type to application/octet-stream to prevent Kafka from trying to decode it as JSON.
            if isinstance(encoded, bytes):
                print(f"➡️  Publishing BYTES message to channel {channel}")
                # kafka_headers.append(('content-type', b'application/octet-stream'))

            if no_confirm:
                future = await self.producer.send(channel, **send_kwargs)
                self.stats.messages_published += 1
                return future  # type: ignore[return-value]

            metadata: RecordMetadata = await self.producer.send_and_wait(
                channel, **send_kwargs
            )
            self.stats.messages_published += 1

            self.logger.debug(
                f'[OK] ➡️  Published: channel={channel} event_id={event_id} '
                f'offset={metadata.offset} partition={metadata.partition}'
            )

            # Match interface return type (Future[M|None] | None).
            done: asyncio.Future[RecordMetadata | None] = asyncio.get_running_loop().create_future()
            done.set_result(metadata)
            return done
        except Exception as exc:
            report_error(
                exc,
                title='➡️  Kafka Message Publish Error',
                extra_context={'channel': channel},
                logger=self.logger,
            )
            raise

    # -----------------------------------------------------------------------
    # Dynamic subscriptions
    # -----------------------------------------------------------------------

    async def subscribe(
        self,
        channel: str,
        handler: MessageHandler,
        *,
        consumer_group: Optional[str] = None,
        from_beginning: bool = False,
        **kwargs: Any,
    ) -> str:
        """
        Subscribe *handler* to *channel* with a dedicated consumer.

        When ``consumer_group`` is ``None`` a unique fan-out group is created
        so the subscriber receives every message. When a shared group is
        supplied, standard Kafka consumer-group balancing applies.
        """
        if not self.running:
            raise RuntimeError('Service not running. Call start_producer() first.')

        sub_id = str(uuid.uuid4())
        # cfg = self._config
        resolved_group_id: str = consumer_group or self.get_consumer_group_id()
        resolved_auto_offset = 'earliest' if from_beginning else 'latest'

        # consumer = AIOKafkaConsumer(
        #     channel,
        #     bootstrap_servers=self.kafka_bootstrap_servers,
        #     group_id=resolved_group_id,
        #     auto_offset_reset=resolved_auto_offset,
        #     enable_auto_commit=self.auto_commit,
        #     **get_aiokafka_security_kwargs(self.security_config),
        # )
        # await consumer.start()

        consumer = self.consumer

        async def _consume_loop() -> None:
            try:
                async for record in consumer:
                    if not self.running:
                        break
                    if record.value is None:
                        self.logger.warning(
                            f'Skipping null message: channel={channel} '
                            f'partition={record.partition} offset={record.offset}'
                        )
                        continue
                    try:
                        decoded = await self._decode_message(channel, record.value)
                        await handler(decoded)
                    except Exception as exc:
                        report_error(
                            exc,
                            title='Kafka Subscription Handler Error',
                            extra_context={'sub_id': sub_id, 'channel': channel},
                            logger=self.logger,
                        )
            except asyncio.CancelledError:
                self.logger.info(
                    f'Subscription cancelled: sub_id={sub_id} channel={channel}'
                )
            except Exception as exc:
                report_error(
                    exc,
                    title='Kafka Subscription Error',
                    extra_context={'sub_id': sub_id, 'channel': channel},
                    logger=self.logger,
                )
            finally:
                try:
                    await consumer.stop()
                except Exception as exc:
                    self.logger.warning(
                        f'Subscription consumer stop failed: {exc!r}'
                    )

        task = asyncio.create_task(_consume_loop())

        self._subscriptions[sub_id] = _SubscriptionInfo(
            handler=handler,
            topic=channel,
            consumer_group=resolved_group_id,
            from_beginning=from_beginning,
            consumer=consumer,
            task=task,
        )
        self.stats.active_subscriptions = len(self._subscriptions)
        self.logger.info(
            f'⬅️  Subscribed: channel={channel} sub_id={sub_id} group_id={resolved_group_id}, auto_offset_reset={resolved_auto_offset}'
        )
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Cancel a dynamic subscription and stop its consumer."""
        if subscription_id not in self._subscriptions:
            raise KeyError(f'Subscription not found: {subscription_id!r}')

        sub = self._subscriptions.pop(subscription_id)
        self.stats.active_subscriptions = len(self._subscriptions)

        if not sub.task.done():
            sub.task.cancel()
            try:
                await sub.task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self.logger.warning(
                    f'Error awaiting cancelled subscription task: {exc!r}'
                )

        self.logger.info(
            f'⬅️  Unsubscribed: channel={sub.topic} sub_id={subscription_id}'
        )

    # -----------------------------------------------------------------------
    # Channel management (admin)
    # -----------------------------------------------------------------------

    async def create_channel(
        self,
        channel: str,
        num_partitions: int = 1,
        *,
        replication_factor: int = 1,
        retention_hours: int = 168,
        fifo: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Create a Kafka topic. Idempotent: returns ``True`` if it already exists."""
        if not self.admin_client:
            raise RuntimeError('Admin client not initialised. Call start_producer() first.')

        try:
            await self.admin_client.create_topics(
                [
                    NewTopic(
                        name=channel,
                        num_partitions=num_partitions,
                        replication_factor=replication_factor,
                    )
                ]
            )
            self.logger.info(
                f'📋 Channel created: name={channel} partitions={num_partitions} '
                f'replication={replication_factor}'
            )
            return True
        except TopicAlreadyExistsError:
            self.logger.debug(f'Topic already exists: {channel}')
            return True
        except Exception as exc:
            report_error(
                exc,
                title='Kafka Channel Creation Error',
                extra_context={
                    'channel': channel,
                    'num_partitions': num_partitions,
                    'replication_factor': replication_factor,
                },
                logger=self.logger,
            )
            return False

    async def delete_channel(self, channel: str, **kwargs: Any) -> bool:
        """Delete a Kafka topic."""
        if not self.admin_client:
            raise RuntimeError('Admin client not initialised. Call start_producer() first.')
        try:
            await self.admin_client.delete_topics([channel])
            self.logger.info(f'🗑️  Channel deleted: {channel}')
            return True
        except Exception as exc:
            report_error(
                exc,
                title='Kafka Channel Deletion Error',
                extra_context={'channel': channel},
                logger=self.logger,
            )
            return False

    async def list_channels(self, **kwargs: Any) -> list[str]:
        """List Kafka topics, excluding internal topics (``_`` prefix)."""
        if not self.admin_client:
            raise RuntimeError('Admin client not initialised. Call start_producer() first.')
        try:
            metadata = await self.admin_client.list_topics()
            return [t for t in metadata if not t.startswith('_')]
        except Exception as exc:
            report_error(exc, title='Kafka Topic Listing Error', logger=self.logger)
            return []

    # -----------------------------------------------------------------------
    # DLQ publish hook (override of BaseMessagingService)
    # -----------------------------------------------------------------------

    async def _publish_dlq_event(
        self,
        dlq_event: DlqEvent,
        *,
        traceparent: Optional[str] = None,
        correlation_id: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        if not self.dlq_enabled:
            self.logger.warning('DLQ is disabled. Skipping publish.')
            return None
        if not self.dlq_producer:
            raise RuntimeError(
                'DLQ producer not initialised. Ensure DLQ_ENABLE=true and '
                'start_producer() was called.'
            )

        dlq_topic = self.dlq_topic
        encoded = await self._encode_message(dlq_topic, dlq_event)

        merged: dict[str, str] = {}
        if traceparent:
            merged['traceparent'] = traceparent
        if correlation_id:
            merged['correlation_id'] = correlation_id
        if headers:
            merged.update(headers)

        return await self.dlq_producer.send(
            dlq_topic,
            value=encoded,
            headers=AiokafkaHelper.to_aiokafka_headers(merged),
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _encode_message(
        self, topic: str, message: BaseSendableMessage
    ) -> Any:
        """Encode an event/dict to wire bytes (or Avro record)."""
        return await self.msg_encoder.encode_msg(
            message, channel=topic, sr_encoder=self._schema_registry_encoder
        )

    async def _decode_message(self, topic: str, raw: bytes) -> BaseEvent:
        """Decode raw Kafka bytes back into a ``BaseEvent``."""
        return await self.msg_encoder.decode_msg(raw, channel=topic, sr_encoder=self._schema_registry_encoder)  # type: ignore
