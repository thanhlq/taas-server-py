"""
🧪 Unit tests for FastStreamKafkaMessagingService

Tests use ``TestKafkaBroker`` for in-memory message routing and
``unittest.mock`` for dependency isolation.

Run:
    uv run pytest libs/messaging_faststream/tests/test_faststream_messaging.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from foundation.messaging.utils.messaging_config import MessagingConfig
from foundation.messaging.utils.msg_encoder import MsgEncoder

from ..conftest import make_base_event, make_mock_config


def _msgpack_encoder() -> MsgEncoder:
    """Construct a fresh MsgEncoder using msgpack pack/unpack."""
    cfg = MessagingConfig(message_encoding='msgpack', message_field_encoding='msgpack')
    return MsgEncoder(config=cfg)


def _encode_event_bytes(encoder: MsgEncoder, event: Any) -> bytes:
    """Pack an event to msgpack bytes via the encoder."""
    payload = event.as_dict() if hasattr(event, 'as_dict') else event
    return encoder.msgpack_pack(payload)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    return make_mock_config()


@pytest.fixture
def mock_event_processor():
    """Mock EventProcessorFast that always returns a successful result."""
    processor = MagicMock()

    success_result = MagicMock()
    success_result.success = True
    success_result.error = None
    success_result.processing_time_ms = 5
    success_result.handler_name = 'test_handler'

    processor.process_event = AsyncMock(return_value=success_result)
    processor.cleanup = AsyncMock()
    return processor


@pytest.fixture
def mock_tracing():
    """Mock TracingFactory that does nothing."""
    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)
    factory = MagicMock()
    factory.start_span = MagicMock(return_value=span)
    factory.get_traceparent = MagicMock(return_value='00-abc-def-01')
    return factory


@pytest_asyncio.fixture
async def service(mock_config, mock_event_processor, mock_tracing):
    """
    Create a ``FastStreamKafkaMessagingService`` with all external
    dependencies mocked.

    The service is NOT started — tests that need a running broker should
    use ``TestKafkaBroker`` or call ``await service.start_producer()``.
    """
    from messaging_faststream.faststream_aiokafka_impl import (
        FastStreamKafkaMessagingService,
    )

    mock_logger = MagicMock()

    with (
        patch(
            'core.messaging.base_messaging.get_app_settings',
            return_value=mock_config,
        ),
        patch(
            'messaging_faststream.faststream_aiokafka_impl.EventProcessor',
            return_value=mock_event_processor,
        ),
        patch(
            'messaging_faststream.faststream_aiokafka_impl.TracingFactory',
            return_value=mock_tracing,
        ),
        # Patch out the service-locator logger lookup used in AbstractService.logger
        patch(
            'core.services.base.AbstractService.logger',
            new_callable=lambda: property(lambda self: mock_logger),
        ),
    ):
        svc = FastStreamKafkaMessagingService()
        # Force real MsgEncoder (msgpack) so encode/decode paths exercise
        # production code instead of a test-only stub.
        svc._msg_encoder = _msgpack_encoder()
        yield svc


@pytest_asyncio.fixture
async def started_service(service):
    """Service with producer started (broker connected)."""
    with patch.object(service._broker, 'connect', new=AsyncMock()):
        # Mock admin client
        mock_admin = AsyncMock()
        mock_admin.start = AsyncMock()
        mock_admin.close = AsyncMock()
        mock_admin.create_topics = AsyncMock()
        mock_admin.delete_topics = AsyncMock()
        mock_admin.list_topics = AsyncMock(
            return_value=['topic.a', 'topic.b', '_internal']
        )

        with patch(
            'messaging_faststream.faststream_aiokafka_impl.AIOKafkaAdminClient',
            return_value=mock_admin,
        ):
            await service.start_producer()
            service._mock_admin = mock_admin
            yield service


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for service startup and shutdown."""

    @pytest.mark.asyncio
    async def test_start_producer_connects_broker(self, service):
        """start_producer() should call broker.connect() and set running=True."""
        with (
            patch.object(service._broker, 'connect', new=AsyncMock()) as mock_connect,
            patch(
                'messaging_faststream.faststream_aiokafka_impl.AIOKafkaAdminClient',
                return_value=AsyncMock(start=AsyncMock()),
            ),
        ):
            await service.start_producer()
            mock_connect.assert_awaited_once()
            assert service.running is True

    @pytest.mark.asyncio
    async def test_start_consumer_requires_producer(self, service):
        """start_consumer() must raise when called before start_producer()."""
        with pytest.raises(RuntimeError, match='start_producer'):
            await service.start_consumer()

    @pytest.mark.asyncio
    async def test_start_consumer_configures_topics(self, started_service, mock_config):
        """start_consumer() records configured topics."""
        await started_service.start_consumer()
        for topic in mock_config.KAFKA_TOPICS:
            assert topic in started_service.configured_topics

    @pytest.mark.asyncio
    async def test_astop_sets_running_false(self, started_service):
        """astop() should mark the service as stopped."""
        with patch.object(started_service._broker, 'close', new=AsyncMock()):
            await started_service.astop()
        assert started_service.running is False

    @pytest.mark.asyncio
    async def test_astop_closes_admin_client(self, started_service):
        """astop() should close the admin client."""
        with patch.object(started_service._broker, 'close', new=AsyncMock()):
            await started_service.astop()
        started_service._mock_admin.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Publishing tests
# ---------------------------------------------------------------------------


class TestPublish:
    """Tests for message publishing."""

    @pytest.mark.asyncio
    async def test_publish_sends_encoded_bytes(self, started_service):
        """publish() should encode the event and call broker.publish()."""
        from faststream.kafka.testing import TestKafkaBroker

        event = make_base_event('user.created', {'user_id': 'u1'})
        received_bodies: list[Any] = []

        @started_service._broker.subscriber('test.events')
        async def _capture(msg: Any) -> None:
            received_bodies.append(msg)

        async with TestKafkaBroker(started_service._broker):
            await started_service.publish('test.events', event)

        assert len(received_bodies) == 1

    @pytest.mark.asyncio
    async def test_publish_increments_stats(self, started_service):
        """publish() should increment messages_published counter."""
        from faststream.kafka.testing import TestKafkaBroker

        event = make_base_event()
        before = started_service.stats['messages_published']

        async with TestKafkaBroker(started_service._broker):
            await started_service.publish('test.events', event)

        assert started_service.stats['messages_published'] == before + 1

    @pytest.mark.asyncio
    async def test_publish_includes_traceparent_header(
        self, started_service, mock_tracing
    ):
        """publish() should include a traceparent header when one is provided."""
        from faststream.kafka.testing import TestKafkaBroker

        captured_headers: list[dict] = []

        # Capture headers from the published message via the test broker
        original_publish = started_service._broker.publish

        async def _spy_publish(msg, *, topic, headers=None, **kw):
            captured_headers.append(headers or {})
            return await original_publish(msg, topic=topic, headers=headers, **kw)

        event = make_base_event()

        async with TestKafkaBroker(started_service._broker):
            with patch.object(
                started_service._broker, 'publish', new=AsyncMock(wraps=_spy_publish)
            ):
                await started_service.publish('test.events', event, traceparent='00-abc-def-01')

        assert any('traceparent' in h for h in captured_headers)


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe tests
# ---------------------------------------------------------------------------


class TestSubscribe:
    """Tests for dynamic subscription management."""

    @pytest.mark.asyncio
    async def test_subscribe_returns_subscription_id(self, started_service):
        """subscribe() should return a non-empty string subscription ID."""

        async def _noop(event: Any) -> None:
            pass

        sub_id = await started_service.subscribe('test.events', _noop)
        assert isinstance(sub_id, str) and sub_id

    @pytest.mark.asyncio
    async def test_subscribe_updates_active_subscriptions_stat(self, started_service):
        """subscribe() should increment active_subscriptions in stats."""

        async def _noop(event: Any) -> None:
            pass

        before = started_service.stats['active_subscriptions']
        await started_service.subscribe('test.events', _noop)
        assert started_service.stats['active_subscriptions'] == before + 1

    @pytest.mark.asyncio
    async def test_subscribe_dispatches_to_handler(self, service):
        """Published messages should be dispatched to the registered handler."""
        from faststream.kafka.testing import TestKafkaBroker

        received: list[Any] = []

        async def _collect(event: Any) -> None:
            received.append(event)

        # Subscribe before TestKafkaBroker so the subscriber is initialized during broker.start()
        await service.subscribe('test.events', _collect)
        event = make_base_event('user.updated', {'user_id': 'u2'})

        async with TestKafkaBroker(service._broker):
            await service.publish('test.events', event)
            # Brief pause to allow async handler to complete
            await asyncio.sleep(0.1)

        # Handler should have been dispatched at least once
        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_multiple_subscriptions_same_topic(self, service):
        """Multiple subscribe() calls on the same topic are all dispatched."""
        from faststream.kafka.testing import TestKafkaBroker

        received_a: list[Any] = []
        received_b: list[Any] = []

        async def handler_a(event: Any) -> None:
            received_a.append(event)

        async def handler_b(event: Any) -> None:
            received_b.append(event)

        # Subscribe before TestKafkaBroker so subscribers are initialized during broker.start()
        await service.subscribe('test.events', handler_a, consumer_group='test-group-a')
        await service.subscribe('test.events', handler_b, consumer_group='test-group-b')
        event = make_base_event()

        async with TestKafkaBroker(service._broker):
            await service.publish('test.events', event)
            await asyncio.sleep(0.1)

        # Both handlers should have been called at least once
        assert len(received_a) >= 1
        assert len(received_b) >= 1

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(self, started_service):
        """unsubscribe() should decrement active_subscriptions."""

        async def _noop(event: Any) -> None:
            pass

        sub_id = await started_service.subscribe('test.events', _noop)
        before = started_service.stats['active_subscriptions']

        await started_service.unsubscribe(sub_id)
        assert started_service.stats['active_subscriptions'] == before - 1

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_id_raises(self, started_service):
        """unsubscribe() should raise KeyError for unknown IDs."""
        with pytest.raises(KeyError):
            await started_service.unsubscribe('does-not-exist')


# ---------------------------------------------------------------------------
# Main-loop processing tests (EventProcessor)
# ---------------------------------------------------------------------------


class TestEventProcessorDispatch:
    """Tests for the main worker loop dispatch path."""

    @pytest.mark.asyncio
    async def test_process_message_calls_event_processor(
        self, started_service, mock_event_processor
    ):
        """_process_message() should call EventProcessor.process_event()."""
        # The service uses its own event_processor attribute; route mock through it.
        started_service.event_processor = mock_event_processor

        event = make_base_event()
        encoded = _encode_event_bytes(started_service.msg_encoder, event)

        await started_service._process_message(
            'test.events', encoded, MagicMock(headers={})
        )

        mock_event_processor.process_event.assert_awaited()

    @pytest.mark.asyncio
    async def test_decode_error_increments_failed_stats(self, started_service):
        """A corrupt message should increment messages_failed and NOT raise."""

        before = started_service.stats['messages_failed']
        # Pass garbage bytes that MsgEncoder cannot decode
        await started_service._process_message(
            'test.events',
            b'\xff\xfe corrupted bytes \x00',
            MagicMock(headers={}),
        )
        assert started_service.stats['messages_failed'] == before + 1

    @pytest.mark.asyncio
    async def test_null_message_is_skipped(self, started_service):
        """A None raw message should be skipped without error."""

        before = started_service.stats['messages_failed']
        await started_service._process_message(
            'test.events', None, MagicMock(headers={})
        )
        assert started_service.stats['messages_failed'] == before  # unchanged

    @pytest.mark.asyncio
    async def test_dlq_sent_on_max_retries(self, started_service, mock_event_processor):
        """Exhausting MAX_RETRIES should trigger DLQ publish."""
        # Route the mock processor used in this test into the service so the
        # failure branch is exercised.
        started_service.event_processor = mock_event_processor

        # The DLQ branch is gated on messaging_config.dlq_enabled; force-enable
        # it here without rebuilding the whole config.
        object.__setattr__(started_service.messaging_config, 'dlq_enabled', True)

        # Configure processor to return failure
        failure_result = MagicMock()
        failure_result.success = False
        failure_result.error = RuntimeError('handler failed')
        failure_result.handler_name = 'my_handler'
        mock_event_processor.process_event.return_value = failure_result

        event = make_base_event()
        # Simulate retry count exhausted
        event.retry_count = started_service.messaging_config.max_retries

        encoded = _encode_event_bytes(started_service.msg_encoder, event)

        before_dlq = started_service.stats['messages_dlq']

        with patch.object(
            started_service, 'send_to_dlq', new=AsyncMock()
        ) as mock_dlq:
            await started_service._process_message(
                'test.events',
                encoded,
                MagicMock(headers={}),
            )
            mock_dlq.assert_awaited_once()

        assert started_service.stats['messages_dlq'] == before_dlq + 1


# ---------------------------------------------------------------------------
# Channel management tests
# ---------------------------------------------------------------------------


class TestChannelManagement:
    """Tests for topic create / delete / list operations."""

    @pytest.mark.asyncio
    async def test_create_channel_returns_true(self, started_service):
        """create_channel() should return True on success."""
        result = await started_service.create_channel('new.topic')
        assert result is True
        started_service._mock_admin.create_topics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_channel_idempotent_on_existing(self, started_service):
        """create_channel() should return True when the topic already exists."""
        from aiokafka.errors import TopicAlreadyExistsError

        started_service._mock_admin.create_topics.side_effect = (
            TopicAlreadyExistsError()
        )
        result = await started_service.create_channel('existing.topic')
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_channel_returns_true(self, started_service):
        """delete_channel() should return True on success."""
        result = await started_service.delete_channel('old.topic')
        assert result is True
        started_service._mock_admin.delete_topics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_channels_excludes_internal(self, started_service):
        """list_channels() should omit topics starting with '_'."""
        topics = await started_service.list_channels()
        assert '_internal' not in topics
        assert 'topic.a' in topics
        assert 'topic.b' in topics

    @pytest.mark.asyncio
    async def test_create_channel_requires_producer(self, service):
        """create_channel() should raise before start_producer() is called."""
        with pytest.raises(RuntimeError):
            await service.create_channel('any.topic')


# ---------------------------------------------------------------------------
# Statistics tests
# ---------------------------------------------------------------------------


class TestStats:
    """Tests for service statistics."""

    def test_get_stats_returns_expected_keys(self, service):
        """get_stats() should include all required statistics keys."""
        stats = service.get_stats()
        required = {
            'messages_published',
            'messages_processed',
            'messages_failed',
            'messages_retried',
            'messages_dlq',
            'running',
            'active_subscriptions',
        }
        assert required.issubset(stats.keys())

    def test_get_stats_initial_counts_are_zero(self, service):
        """All counters should start at zero."""
        stats = service.get_stats()
        for key in ('messages_published', 'messages_processed', 'messages_failed'):
            assert stats[key] == 0

    def test_get_stats_running_false_initially(self, service):
        """running should be False before start_producer()."""
        assert service.get_stats()['running'] is False


# ---------------------------------------------------------------------------
# Schema Registry integration (unit)
# ---------------------------------------------------------------------------


class TestSchemaRegistryIntegration:
    """Tests for the AsyncSchemaRegistryEncoder path."""

    @pytest.mark.asyncio
    async def test_publish_uses_schema_registry_encoder(self, mock_config):
        """When schema_registry_config is set, AsyncSchemaRegistryEncoder is used."""
        from core.messaging.sr.schema_registry_fast import SchemaRegistryConfig
        from messaging_faststream.faststream_aiokafka_impl import (
            FastStreamKafkaMessagingService,
        )

        sr_config = SchemaRegistryConfig(url='http://localhost:8081')
        avro_schema = {
            'type': 'record',
            'name': 'TestEvent',
            'fields': [
                {'name': 'event_id', 'type': 'string'},
                {'name': 'event_type', 'type': 'string'},
            ],
        }
        mock_logger = MagicMock()

        mock_config.MESSAGE_ENCODING = 'schema-registry-avro'
        mock_config.KAFKA_SCHEMA_REGISTRY_URL = sr_config.url
        mock_config.KAFKA_SCHEMA_REGISTRY_USERNAME = None
        mock_config.KAFKA_SCHEMA_REGISTRY_PASSWORD = None

        with (
            patch(
                'core.messaging.base_messaging.get_app_settings',
                return_value=mock_config,
            ),
            patch(
                'core.services.base.AbstractService.logger',
                new_callable=lambda: property(lambda self: mock_logger),
            ),
        ):
            svc = FastStreamKafkaMessagingService(
                avro_schemas={'test.events': avro_schema},
            )

        assert svc._schema_registry_encoder is not None

    @pytest.mark.asyncio
    async def test_register_topic_schema_requires_config(self, service):
        """register_schema() raises when no SR config provided."""
        with pytest.raises(RuntimeError, match='SchemaRegistryConfig'):
            service.register_schema('some.topic', {'type': 'null'})
