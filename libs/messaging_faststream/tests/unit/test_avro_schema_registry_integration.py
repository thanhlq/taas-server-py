"""
Integration tests: FastStream + Confluent Schema Registry + UserDirectoryCreatedEvent

Tests exercise the full Avro encode/decode pipeline through
``AsyncSchemaRegistryEncoder`` and ``FastStreamKafkaMessagingService._encode_message``
/ ``_decode_message``.

Requirements (real services):
    - Confluent Schema Registry on http://localhost:8081
    - Confluent Kafka on localhost:9092  (only for full-pipeline tests)

Run all integration tests:
    uv run pytest libs/messaging_faststream/tests/test_avro_schema_registry_integration.py -v -m integration

Run only encoder-level tests (Schema Registry only, no Kafka needed):
    uv run pytest libs/messaging_faststream/tests/test_avro_schema_registry_integration.py::TestEncoderIntegration -v -m integration
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_repo_root = Path(__file__).parent.parent.parent.parent
_core_src = _repo_root / 'libs' / 'core' / 'src'
_fs_src = Path(__file__).parent.parent / 'src'

for _p in (_core_src, _fs_src):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KAFKA_BOOTSTRAP = 'localhost:9092'
SCHEMA_REGISTRY_URL = 'http://localhost:8081'
TEST_TOPIC = 'iam.user.registered'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _schema_registry_available() -> bool:
    """Return True when the local Schema Registry responds on port 8081."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f'{SCHEMA_REGISTRY_URL}/subjects')
            return r.is_success
    except Exception:
        return False


def _make_sr_mock_config() -> MagicMock:
    """Return a mock ``AppSetting`` with Schema Registry and Avro encoding enabled."""
    from ..conftest import make_mock_config

    config = make_mock_config(
        topics=[TEST_TOPIC],
        bootstrap_servers=KAFKA_BOOTSTRAP,
        consumer_enable=False,
        encoding='schema-registry-avro',
    )
    config.KAFKA_CONSUMER_GROUP_ID = 'test-sr-int-group'
    config.KAFKA_SCHEMA_REGISTRY_URL = SCHEMA_REGISTRY_URL
    config.kafka_config = {
        'bootstrap_servers': [KAFKA_BOOTSTRAP],
        'group_id': 'test-sr-int-group',
        'auto_offset_reset': 'earliest',
        'enable_auto_commit': False,
    }
    return config


def _build_service_with_sr(avro_schemas: dict[str, dict]):
    """
    Construct a ``FastStreamKafkaMessagingService`` with Schema Registry enabled.

    All external dependencies (app config, tracing, EventProcessor) are mocked
    so the service can be instantiated without a running Kafka broker.
    """
    from messaging_faststream.faststream_aiokafka_impl import (
        FastStreamKafkaMessagingService,
    )

    mock_logger = MagicMock()
    mock_config = _make_sr_mock_config()

    # EventProcessor constructor is patched to avoid touching Kafka at init
    mock_ep = MagicMock()
    mock_ep.process_event = AsyncMock()
    mock_ep.cleanup = AsyncMock()

    with (
        patch('core.messaging.base_messaging.get_app_settings', return_value=mock_config),
        patch('messaging_faststream.faststream_aiokafka_impl.EventProcessor', return_value=mock_ep),
        patch(
            'core.services.base.AbstractService.logger',
            new_callable=lambda: property(lambda self: mock_logger),  # type: ignore[arg-type]
        ),
    ):
        svc = FastStreamKafkaMessagingService(avro_schemas=avro_schemas)

    # Reattach logger so post-construction calls don't fail
    svc._mock_logger = mock_logger  # type: ignore[attr-defined]
    return svc, mock_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_dir_schema() -> dict:
    """Return the Avro schema for ``UserDirectoryCreatedEvent``."""
    from core.iam.events.iam_events import UserDirectoryCreatedEvent

    return UserDirectoryCreatedEvent.avro_schema_to_python()


@pytest.fixture
def sr_encoder(user_dir_schema):
    """
    ``AsyncSchemaRegistryEncoder`` pointed at the real local Schema Registry
    with ``UserDirectoryCreatedEvent`` schema pre-loaded.
    """
    from core.messaging.sr.schema_registry_fast import (
        SchemaRegistryConfig,
        SchemaRegistryEncoder,
    )

    config = SchemaRegistryConfig(url=SCHEMA_REGISTRY_URL)
    return SchemaRegistryEncoder(
        registry_config=config,
        avro_schemas={TEST_TOPIC: user_dir_schema},
    )


@pytest.fixture
def sample_event():
    """A ``UserDirectoryCreatedEvent`` with representative field values."""
    from core.iam.events.iam_constants import IamEvents
    from core.iam.events.iam_events import UserDirectoryCreatedEvent

    return UserDirectoryCreatedEvent(
        event_type=IamEvents.USER_DIRECTORY_CREATED.value,
        email='alice@example.com',
        username='alice',
        realm_name='master',
    )


# ---------------------------------------------------------------------------
# TestEncoderIntegration — Schema Registry encode/decode (no Kafka required)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEncoderIntegration:
    """
    Tests for ``AsyncSchemaRegistryEncoder`` against the real Confluent Schema Registry.

    These tests only need the Schema Registry to be running; no Kafka broker is required.
    """

    @pytest.mark.asyncio
    async def test_schema_auto_registered_on_first_encode(self, sr_encoder, sample_event):
        """Encoding an event for the first time should register its schema in the registry."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        await sr_encoder.encode_event(TEST_TOPIC, sample_event.as_dict())

        subjects = await sr_encoder._client.list_subjects()
        assert f'{TEST_TOPIC}-value' in subjects, (
            f'Expected subject "{TEST_TOPIC}-value" to be registered, got: {subjects}'
        )

    @pytest.mark.asyncio
    async def test_encode_returns_confluent_wire_format(self, sr_encoder, sample_event):
        """Encoded bytes must start with the Confluent magic byte (0x00)."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        raw = await sr_encoder.encode_event(TEST_TOPIC, sample_event.as_dict())

        assert isinstance(raw, bytes), 'encode_event must return bytes'
        assert raw[0:1] == b'\x00', 'First byte must be Confluent magic byte 0x00'

    @pytest.mark.asyncio
    async def test_decode_returns_original_fields(self, sr_encoder, sample_event):
        """Decoding encoded bytes must reproduce every field of the original event."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        raw = await sr_encoder.encode_event(TEST_TOPIC, sample_event.as_dict())
        decoded: dict[str, Any] = await sr_encoder.decode(TEST_TOPIC, raw)

        assert decoded['email'] == 'alice@example.com'
        assert decoded['username'] == 'alice'
        assert decoded['realm_name'] == 'master'
        assert decoded['event_type'] == 'user.directory_created'

    @pytest.mark.asyncio
    async def test_second_encode_uses_cached_schema_id(self, sr_encoder, sample_event):
        """A second call for the same topic should hit the in-memory cache (no extra HTTP)."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        raw1 = await sr_encoder.encode_event(TEST_TOPIC, sample_event.as_dict())
        raw2 = await sr_encoder.encode_event(TEST_TOPIC, sample_event.as_dict())

        # Both messages must have the same schema ID embedded (bytes 1-5)
        assert raw1[1:5] == raw2[1:5], 'Schema ID should be identical across calls'

    @pytest.mark.asyncio
    async def test_encode_decode_with_msgpack_payload(self, sr_encoder):
        """Round-trip a ``UserDirectoryCreatedEvent`` with a msgpack-encoded payload."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        from core.iam.events.iam_constants import IamEvents
        from core.iam.events.iam_events import UserDirectoryCreatedEvent
        from core.messaging.utils.messaging_config import MessagingConfig
        from core.messaging.utils.msg_encoder import MsgEncoder

        msg_encoder = MsgEncoder(
            config=MessagingConfig(
                message_encoding='msgpack', message_field_encoding='msgpack'
            )
        )
        payload = {
            'user': {'email': 'bob@acme.com', 'username': 'bob'},
            'tenant': {'id': 'tenant-1', 'name': 'Acme'},
        }
        event = UserDirectoryCreatedEvent(
            event_type=IamEvents.USER_DIRECTORY_CREATED.value,
            email='bob@acme.com',
            username='bob',
            realm_name='acme',
            payload=msg_encoder.msgpack_pack(payload),
        )

        raw = await sr_encoder.encode_event(TEST_TOPIC, event.as_dict())
        decoded = await sr_encoder.decode(TEST_TOPIC, raw)

        assert decoded['email'] == 'bob@acme.com'
        assert isinstance(decoded['payload'], bytes)
        restored = msg_encoder.msgpack_unpack(decoded['payload'])
        assert restored == payload


# ---------------------------------------------------------------------------
# TestServicePipelineIntegration — full _encode_message / _decode_message cycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestServicePipelineIntegration:
    """
    Tests for the encode → decode pipeline inside ``FastStreamKafkaMessagingService``.

    These tests require the Confluent Schema Registry to be running but do NOT
    need a live Kafka broker — ``_encode_message`` and ``_decode_message`` are
    called directly without publishing to Kafka.
    """

    @pytest.mark.asyncio
    async def test_encode_message_produces_wire_format_bytes(self, user_dir_schema, sample_event):
        """``_encode_message`` should return Confluent wire-format bytes."""
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        svc, _ = _build_service_with_sr({TEST_TOPIC: user_dir_schema})

        raw = await svc._encode_message(TEST_TOPIC, sample_event)

        assert isinstance(raw, bytes)
        assert raw[0:1] == b'\x00', 'Expected Confluent magic byte at position 0'

    @pytest.mark.asyncio
    async def test_decode_message_reconstructs_typed_event(self, user_dir_schema, sample_event):
        """
        ``_decode_message`` should reconstruct a typed ``UserDirectoryCreatedEvent``
        when the event type is registered in ``_event_type_registry``.
        """
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        from core.iam.events.iam_constants import IamEvents
        from core.iam.events.iam_events import UserDirectoryCreatedEvent

        svc, _ = _build_service_with_sr({TEST_TOPIC: user_dir_schema})
        svc.register_event_serializer(UserDirectoryCreatedEvent)

        raw = await svc._encode_message(TEST_TOPIC, sample_event)
        decoded = await svc._decode_message(TEST_TOPIC, raw)

        assert isinstance(decoded, UserDirectoryCreatedEvent), (
            f'Expected UserDirectoryCreatedEvent, got {type(decoded).__name__}'
        )
        assert decoded.email == 'alice@example.com'
        assert decoded.username == 'alice'
        assert decoded.realm_name == 'master'
        assert decoded.event_type == IamEvents.USER_DIRECTORY_CREATED.value

    @pytest.mark.asyncio
    async def test_decode_message_falls_back_to_base_event_when_type_not_registered(
        self, user_dir_schema, sample_event
    ):
        """
        When ``event_type`` is not in ``_event_type_registry``, ``_decode_message``
        should fall back to ``BaseEvent``.
        """
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')


        svc, _ = _build_service_with_sr({TEST_TOPIC: user_dir_schema})
        # Intentionally NOT registering the event type

        raw = await svc._encode_message(TEST_TOPIC, sample_event)
        decoded = await svc._decode_message(TEST_TOPIC, raw)

        # Falls back to BaseEvent — fields shared with BaseEvent should be present
        assert decoded.event_type == 'user.directory_created'

    @pytest.mark.asyncio
    async def test_register_iam_handlers_registers_schema(self, user_dir_schema):
        """
        Calling ``register_iam_schema_registry_schemas()`` with schema registry
        enabled should populate the per-topic Avro schema map on the messaging
        service.
        """
        if not await _schema_registry_available():
            pytest.skip('Confluent Schema Registry not reachable at http://localhost:8081')

        from core.iam.events.handlers import (
            register_iam_handlers,
            register_iam_schema_registry_schemas,
        )
        from core.iam.events.iam_constants import IamTopics

        svc, mock_config = _build_service_with_sr({TEST_TOPIC: user_dir_schema})
        mock_config.CONSUMER_ENABLE = True

        mock_registry = MagicMock()
        mock_logger = MagicMock()

        with (
            patch('core.messaging.base_messaging.get_app_settings', return_value=mock_config),
            patch(
                'core.services.base.AbstractService.logger',
                new_callable=lambda: property(lambda self: mock_logger),  # type: ignore[arg-type]
            ),
        ):
            register_iam_handlers(mock_registry, msg_service=svc)
            register_iam_schema_registry_schemas(svc)

        # The service's encoder should now have IAM topic schemas registered
        assert IamTopics.IAM_USER_REGISTER in svc._schema_registry_encoder.avro_schemas
