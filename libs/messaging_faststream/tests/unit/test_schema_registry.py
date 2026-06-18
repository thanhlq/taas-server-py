"""
🧪 Unit tests for schema_registry.py

All HTTP calls are intercepted with ``respx`` (async httpx mock).

Run:
    uv run pytest libs/messaging_faststream/tests/unit/test_schema_registry.py -v
"""

from __future__ import annotations

import io
import json
import struct

import fastavro
import pytest
import respx
from httpx import Response
from core.messaging.sr import (
    ConfluentWireFormat,
    SchemaNotFoundError,
    SchemaRegistryClient,
    SchemaRegistryConfig,
    SchemaRegistryEncoder,
    SchemaRegistryError,
    WireFormatError,
)
from core.messaging.sr.schema_registry_fast import (
    FastavroSerializer as AvroSchemaRegistrySerializer,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

SIMPLE_AVRO_SCHEMA = {
    'type': 'record',
    'name': 'User',
    'fields': [
        {'name': 'user_id', 'type': 'string'},
        {'name': 'email', 'type': 'string'},
    ],
}

SAMPLE_RECORD = {'user_id': 'u-001', 'email': 'test@example.com'}

REGISTRY_URL = 'http://localhost:8081'


def _avro_bytes(record: dict, schema: dict) -> bytes:
    """Serialize *record* to raw Avro bytes (no wire format)."""
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, fastavro.parse_schema(schema), record)
    return buf.getvalue()


def _wire_encode(schema_id: int, avro_payload: bytes) -> bytes:
    return b'\x00' + struct.pack('>I', schema_id) + avro_payload


# ---------------------------------------------------------------------------
# ConfluentWireFormat
# ---------------------------------------------------------------------------


class TestConfluentWireFormat:
    """Low-level wire-format encode / decode."""

    def test_encode_decode_round_trip(self):
        payload = b'avro-data-here'
        wire = ConfluentWireFormat.encode(42, payload)
        schema_id, decoded = ConfluentWireFormat.decode(wire)
        assert schema_id == 42
        assert decoded == payload

    def test_encode_starts_with_magic_byte(self):
        wire = ConfluentWireFormat.encode(1, b'data')
        assert wire[0:1] == b'\x00'

    def test_encode_schema_id_big_endian(self):
        wire = ConfluentWireFormat.encode(256, b'data')
        (schema_id,) = struct.unpack('>I', wire[1:5])
        assert schema_id == 256

    def test_decode_invalid_magic_byte_raises(self):
        bad = b'\x01' + struct.pack('>I', 1) + b'data'
        with pytest.raises(WireFormatError, match='magic byte'):
            ConfluentWireFormat.decode(bad)

    def test_decode_too_short_raises(self):
        with pytest.raises(WireFormatError):
            ConfluentWireFormat.decode(b'\x00\x00')

    def test_encode_schema_id_zero(self):
        wire = ConfluentWireFormat.encode(0, b'')
        schema_id, payload = ConfluentWireFormat.decode(wire)
        assert schema_id == 0
        assert payload == b''


# ---------------------------------------------------------------------------
# SchemaRegistryConfig
# ---------------------------------------------------------------------------


class TestSchemaRegistryConfig:
    def test_auth_none_when_no_credentials(self):
        config = SchemaRegistryConfig(url=REGISTRY_URL)
        assert config.auth is None

    def test_auth_returns_tuple_with_credentials(self):
        config = SchemaRegistryConfig(
            url=REGISTRY_URL, username='user', password='pass'
        )
        assert config.auth == ('user', 'pass')

    def test_url_stored_correctly(self):
        config = SchemaRegistryConfig(url=REGISTRY_URL)
        assert config.url == REGISTRY_URL


# ---------------------------------------------------------------------------
# SchemaRegistryClient — HTTP interactions
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_config():
    return SchemaRegistryConfig(url=REGISTRY_URL, ssl_verify=False)


@pytest.fixture
def registry_client(registry_config):
    return SchemaRegistryClient(registry_config)


class TestSchemaRegistryClientRegister:
    """register_schema()"""

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_register_returns_schema_id(self, registry_client, respx_mock):
        respx_mock.post('/subjects/my-topic-value/versions').mock(
            return_value=Response(200, json={'id': 7})
        )
        schema_id = await registry_client.register_schema(
            'my-topic-value', SIMPLE_AVRO_SCHEMA
        )
        assert schema_id == 7

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_register_caches_id(self, registry_client, respx_mock):
        respx_mock.post('/subjects/my-topic-value/versions').mock(
            return_value=Response(200, json={'id': 7})
        )
        id1 = await registry_client.register_schema(
            'my-topic-value', SIMPLE_AVRO_SCHEMA
        )
        # Second call should hit cache, not HTTP
        id2 = await registry_client.register_schema(
            'my-topic-value', SIMPLE_AVRO_SCHEMA
        )
        assert id1 == id2 == 7
        # HTTP was only called once
        assert respx_mock.calls.call_count == 1

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_register_raises_on_server_error(self, registry_client, respx_mock):
        respx_mock.post('/subjects/my-topic-value/versions').mock(
            return_value=Response(500, json={'error_code': 50001, 'message': 'oops'})
        )
        with pytest.raises(SchemaRegistryError) as exc_info:
            await registry_client.register_schema('my-topic-value', SIMPLE_AVRO_SCHEMA)
        assert exc_info.value.status_code == 500


class TestSchemaRegistryClientGetSchema:
    """get_schema_by_id() and get_latest_schema()"""

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_get_schema_by_id(self, registry_client, respx_mock):
        respx_mock.get('/schemas/ids/42').mock(
            return_value=Response(200, json={'schema': json.dumps(SIMPLE_AVRO_SCHEMA)})
        )
        schema = await registry_client.get_schema_by_id(42)
        assert schema['type'] == 'record'

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_get_schema_by_id_caches(self, registry_client, respx_mock):
        respx_mock.get('/schemas/ids/42').mock(
            return_value=Response(200, json={'schema': json.dumps(SIMPLE_AVRO_SCHEMA)})
        )
        await registry_client.get_schema_by_id(42)
        await registry_client.get_schema_by_id(42)
        assert respx_mock.calls.call_count == 1

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_get_schema_not_found_raises(self, registry_client, respx_mock):
        respx_mock.get('/schemas/ids/99').mock(
            return_value=Response(
                404, json={'error_code': 40403, 'message': 'Schema not found'}
            )
        )
        with pytest.raises(SchemaNotFoundError):
            await registry_client.get_schema_by_id(99)

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_get_latest_schema(self, registry_client, respx_mock):
        respx_mock.get('/subjects/my-topic-value/versions/latest').mock(
            return_value=Response(
                200,
                json={
                    'id': 10,
                    'version': 1,
                    'schema': json.dumps(SIMPLE_AVRO_SCHEMA),
                },
            )
        )
        schema_id, schema = await registry_client.get_latest_schema('my-topic-value')
        assert schema_id == 10
        assert schema['name'] == 'User'


class TestSchemaRegistryClientMeta:
    """subject_exists(), list_subjects(), delete_subject()"""

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_subject_exists_true(self, registry_client, respx_mock):
        # subject_exists() calls GET /subjects/{subject}/versions/latest
        respx_mock.get('/subjects/my-topic-value/versions/latest').mock(
            return_value=Response(
                200,
                json={'id': 1, 'version': 1, 'schema': '{}'},
            )
        )
        assert await registry_client.subject_exists('my-topic-value') is True

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_subject_exists_false_on_404(self, registry_client, respx_mock):
        # subject_exists() calls GET /subjects/{subject}/versions/latest
        respx_mock.get('/subjects/no-such-subject/versions/latest').mock(
            return_value=Response(
                404,
                json={'error_code': 40401, 'message': 'Subject not found.'},
            )
        )
        assert await registry_client.subject_exists('no-such-subject') is False

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_list_subjects(self, registry_client, respx_mock):
        respx_mock.get('/subjects').mock(
            return_value=Response(200, json=['topic-a-value', 'topic-b-value'])
        )
        subjects = await registry_client.list_subjects()
        assert subjects == ['topic-a-value', 'topic-b-value']

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_delete_subject_soft(self, registry_client, respx_mock):
        respx_mock.delete('/subjects/my-topic-value').mock(
            return_value=Response(200, json=[1, 2])
        )
        versions = await registry_client.delete_subject('my-topic-value')
        assert versions == [1, 2]

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_delete_subject_permanent(self, registry_client, respx_mock):
        # permanent=True appends ?permanent=true to the DELETE path
        respx_mock.delete('/subjects/my-topic-value').mock(
            return_value=Response(200, json=[1])
        )
        versions = await registry_client.delete_subject(
            'my-topic-value', permanent=True
        )
        # The request should have permanent=true in the query string
        assert any(
            'permanent=true' in str(call.request.url) for call in respx_mock.calls
        )
        assert versions == [1]


# ---------------------------------------------------------------------------
# AvroSchemaRegistrySerializer — encode / decode round-trip
# ---------------------------------------------------------------------------


class TestAvroSchemaRegistrySerializer:
    """Full Avro serialization / deserialization via mock Schema Registry."""

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL, assert_all_called=False)
    async def test_serialize_deserialize_round_trip(self, registry_config, respx_mock):
        """serialize() → deserialize() should restore the original record."""
        schema_id = 5
        # Registration mock
        respx_mock.post('/subjects/my-topic-value/versions').mock(
            return_value=Response(200, json={'id': schema_id})
        )
        # Deserialization fetches schema by ID — served from cache after registration,
        # but we add a fallback mock in case cache is not yet populated
        respx_mock.get(f'/schemas/ids/{schema_id}').mock(
            return_value=Response(200, json={'schema': json.dumps(SIMPLE_AVRO_SCHEMA)})
        )

        client = SchemaRegistryClient(registry_config)
        serializer = AvroSchemaRegistrySerializer(registry=client)

        wire = await serializer.serialize('my-topic', SAMPLE_RECORD, SIMPLE_AVRO_SCHEMA)
        restored = await serializer.deserialize(wire)

        assert restored == SAMPLE_RECORD

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL)
    async def test_serialize_produces_valid_wire_format(
        self, registry_config, respx_mock
    ):
        """Wire bytes should start with Confluent magic byte 0x00."""
        respx_mock.post('/subjects/my-topic-value/versions').mock(
            return_value=Response(200, json={'id': 3})
        )

        client = SchemaRegistryClient(registry_config)
        serializer = AvroSchemaRegistrySerializer(registry=client)

        wire = await serializer.serialize('my-topic', SAMPLE_RECORD, SIMPLE_AVRO_SCHEMA)
        assert wire[0:1] == b'\x00'

    @pytest.mark.asyncio
    async def test_deserialize_bad_magic_byte_raises(self, registry_config):
        """Bytes with wrong magic byte should raise WireFormatError."""
        client = SchemaRegistryClient(registry_config)
        serializer = AvroSchemaRegistrySerializer(registry=client)

        with pytest.raises(WireFormatError, match='magic byte'):
            await serializer.deserialize(b'\xff' + b'\x00' * 4 + b'data')


# ---------------------------------------------------------------------------
# AsyncSchemaRegistryEncoder (high-level)
# ---------------------------------------------------------------------------


class TestAsyncSchemaRegistryEncoder:
    """encode_event / decode round-trips through the high-level encoder."""

    @pytest.mark.asyncio
    @respx.mock(base_url=REGISTRY_URL, assert_all_called=False)
    async def test_encode_decode_dict_round_trip(self, registry_config, respx_mock):
        """encode_event() → decode() should restore the original dict."""
        schema_id = 7
        topic = 'users.events'
        avro_schemas = {topic: SIMPLE_AVRO_SCHEMA}

        respx_mock.post(f'/subjects/{topic}-value/versions').mock(
            return_value=Response(200, json={'id': schema_id})
        )
        # Decoding fetches schema by ID — served from in-process cache after
        # registration; add optional fallback for safety
        respx_mock.get(f'/schemas/ids/{schema_id}').mock(
            return_value=Response(200, json={'schema': json.dumps(SIMPLE_AVRO_SCHEMA)})
        )

        encoder = SchemaRegistryEncoder(
            registry_config=registry_config,
            avro_schemas=avro_schemas,
        )
        wire = await encoder.encode_event(topic, SAMPLE_RECORD)
        decoded = await encoder.decode(topic, wire)

        assert decoded == SAMPLE_RECORD

    def test_register_topic_schema_adds_schema(self, registry_config):
        """register_topic_schema() should update the schema map."""
        encoder = SchemaRegistryEncoder(
            registry_config=registry_config,
            avro_schemas={},
        )
        new_schema = {'type': 'null'}
        encoder.register_topic_schema('new.topic', new_schema)
        assert encoder.avro_schemas.get('new.topic') == new_schema

    @pytest.mark.asyncio
    async def test_encode_topic_without_schema_raises(self, registry_config):
        """encode_event() for a topic with no schema should raise ValueError."""
        encoder = SchemaRegistryEncoder(
            registry_config=registry_config,
            avro_schemas={},
        )
        with pytest.raises(ValueError):
            await encoder.encode_event('unknown.topic', {'key': 'val'})
