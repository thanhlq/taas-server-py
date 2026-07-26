"""
🗂️ Confluent Schema Registry Client & Avro Serializer

Implements the Confluent Schema Registry REST API (v1) and the Confluent wire
format for Avro-encoded Kafka messages.

Wire format:
    ┌──────────┬──────────────────────┬──────────────────────────┐
    │ Magic (1)│ Schema ID (4 bytes)  │   Avro payload (N bytes) │
    │  0x00    │  big-endian uint32   │   fastavro schemaless    │
    └──────────┴──────────────────────┴──────────────────────────┘

Usage:
    config = SchemaRegistryConfig(url="http://localhost:8081")
    client = SchemaRegistryClient(config)

    # Register a schema
    schema_id = await client.register_schema("my-topic-value", avro_schema_dict)

    # Serialize with Avro + wire format
    serializer = AvroSchemaRegistrySerializer(client)
    encoded = await serializer.serialize("my-topic", data_dict, avro_schema_dict)

    # Deserialize
    decoded = await serializer.deserialize(encoded)

Schema Registry REST API reference:
    https://docs.confluent.io/platform/current/schema-registry/develop/api.html
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import fastavro
import httpx
from foundation.observability.log_factory import LogFactory

from ...types import BaseSendableMessage
from .confluent import ConfluentWireFormat
from .sr_config import SchemaRegistryConfig
from .types import (
    ISchemaRegistryClient,
    ISchemaRegistryEncoder,
    ISchemaSerializer,
)
from .types import (
    SchemaNotFoundError as _ISchemaNotFoundError,
)
from .types import (
    SchemaRegistryError as _ISchemaRegistryError,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SchemaRegistryError(_ISchemaRegistryError):
    """Raised when a Schema Registry API call fails."""


class SchemaNotFoundError(_ISchemaNotFoundError, SchemaRegistryError):
    """Raised when a schema is not found in the registry."""




# ---------------------------------------------------------------------------
# Schema Registry HTTP Client
# ---------------------------------------------------------------------------


class SchemaRegistryClient(ISchemaRegistryClient):
    """
    Async Confluent Schema Registry HTTP client.

    Implements the REST API described at
    https://docs.confluent.io/platform/current/schema-registry/develop/api.html

    Schema and subject lookups are cached in memory to avoid redundant HTTP
    round-trips on the hot path.

    Args:
        config: Connection configuration.

    Example::

        client = SchemaRegistryClient(SchemaRegistryConfig(url="http://localhost:8081"))

        # Register
        schema_id = await client.register_schema(
            "orders-value",
            {"type": "record", "name": "Order", "fields": [...]}
        )

        # Fetch by ID
        schema = await client.get_schema_by_id(schema_id)
    """

    def __init__(self, config: SchemaRegistryConfig) -> None:
        self._config = config
        # Cache schema_id → parsed schema dict
        self._schema_by_id: dict[int, dict] = {}
        # Cache subject → schema_id for the latest registered version
        self._id_by_subject: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.AsyncClient:
        """Build a configured ``httpx.AsyncClient`` for a single request."""
        kwargs: dict[str, Any] = {
            'base_url': self._config.url,
            'timeout': self._config.timeout_seconds,
            'verify': self._config.ssl_verify,
            'headers': {'Accept': 'application/vnd.schemaregistry.v1+json'},
        }
        if self._config.auth:
            kwargs['auth'] = self._config.auth
        return httpx.AsyncClient(**kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
    ) -> Any:
        """Perform an HTTP request and return the parsed JSON response.

        Raises:
            SchemaRegistryError: On any non-2xx response.
        """
        async with self._build_client() as client:
            response = await client.request(method, path, json=json_body)

        if not response.is_success:
            try:
                detail = response.json()
                message = detail.get('message', response.text)
            except Exception:
                message = response.text
            raise SchemaRegistryError(
                f'Schema Registry error {response.status_code}: {message}',
                status_code=response.status_code,
            )

        return response.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_schema(self, subject: str, schema: dict) -> int:
        """Register *schema* under *subject* and return the schema ID.

        If an identical schema already exists the registry returns the
        existing schema ID without creating a duplicate.

        Args:
            subject: Subject name (e.g. ``"orders-value"``).
            schema: Avro schema as a Python dict.

        Returns:
            The schema ID assigned by the registry.
        """
        # Check cache first (keyed by subject name for the latest registration)
        # This is a best-effort dedup; the registry itself is the source of truth.
        cache_key = f'{subject}:{json.dumps(schema, sort_keys=True)}'
        if cache_key in self._id_by_subject:
            return self._id_by_subject[cache_key]

        payload = {'schema': json.dumps(schema)}
        result = await self._request(
            'POST',
            f'/subjects/{subject}/versions',
            json_body=payload,
        )
        schema_id: int = result['id']
        # Populate caches eagerly
        self._schema_by_id[schema_id] = schema
        self._id_by_subject[cache_key] = schema_id
        return schema_id

    async def get_schema_by_id(self, schema_id: int) -> dict:
        """Fetch and return the Avro schema for *schema_id*.

        Results are cached to avoid repeated network calls on the hot path.

        Args:
            schema_id: Numeric schema ID from the registry.

        Returns:
            Avro schema as a Python dict.

        Raises:
            SchemaNotFoundError: When the schema ID does not exist.
        """
        if schema_id in self._schema_by_id:
            return self._schema_by_id[schema_id]

        try:
            result = await self._request('GET', f'/schemas/ids/{schema_id}')
        except SchemaRegistryError as exc:
            if exc.status_code == 404:
                raise SchemaNotFoundError(f'Schema not found: id={schema_id}') from exc
            raise

        schema = json.loads(result['schema'])
        self._schema_by_id[schema_id] = schema
        return schema

    async def get_latest_schema(self, subject: str) -> tuple[int, dict]:
        """Fetch the latest registered schema version for *subject*.

        Args:
            subject: Subject name.

        Returns:
            ``(schema_id, schema_dict)`` tuple.

        Raises:
            SchemaNotFoundError: When the subject has no registered versions.
        """
        try:
            result = await self._request('GET', f'/subjects/{subject}/versions/latest')
        except SchemaRegistryError as exc:
            if exc.status_code == 404:
                raise SchemaNotFoundError(f'Subject not found: {subject!r}') from exc
            raise

        schema_id: int = result['id']
        schema = json.loads(result['schema'])
        self._schema_by_id[schema_id] = schema
        return schema_id, schema

    async def subject_exists(self, subject: str) -> bool:
        """Return ``True`` if *subject* is registered in the Schema Registry."""
        try:
            await self._request('GET', f'/subjects/{subject}/versions/latest')
            return True
        except SchemaRegistryError as exc:
            if exc.status_code == 404:
                return False
            raise

    async def list_subjects(self) -> list[str]:
        """Return a list of all subjects registered in the Schema Registry."""
        result = await self._request('GET', '/subjects')
        return result  # list[str]

    async def delete_subject(
        self, subject: str, *, permanent: bool = False
    ) -> list[int]:
        """Delete all versions of *subject*.

        Args:
            subject: Subject name.
            permanent: When ``True`` permanently delete (hard delete) the
                subject, bypassing the soft-delete default. Defaults to ``False``.

        Returns:
            List of deleted schema version numbers.
        """
        path = f'/subjects/{subject}'
        if permanent:
            path += '?permanent=true'
        result = await self._request('DELETE', path)
        self._id_by_subject.pop(subject, None)
        return result  # list[int]


# ---------------------------------------------------------------------------
# Avro Serializer
# ---------------------------------------------------------------------------


@dataclass
class FastavroSerializer(ISchemaSerializer):
    """
    High-level Avro serializer using the Confluent Schema Registry.

    Combines ``fastavro`` for Avro encoding/decoding with
    ``SchemaRegistryClient`` for schema management and
    ``ConfluentWireFormat`` for Kafka wire format compliance.

    **Schema ID caching**: Each ``(subject, schema_fingerprint)`` is cached
    locally so schema registration is only performed once per unique schema.

    **Subject naming convention**: Uses the *TopicNameStrategy* by default —
    ``<topic>-value`` for values and ``<topic>-key`` for keys, matching the
    Confluent Kafka Java client default.

    Args:
        registry: Configured ``SchemaRegistryClient``.
        subject_suffix: Either ``"value"`` (default) or ``"key"``.

    Example::

        client = SchemaRegistryClient(config)
        serializer = AvroSchemaRegistrySerializer(client)

        # Encode
        avro_schema = {
            "type": "record", "name": "User",
            "fields": [{"name": "id", "type": "string"}]
        }
        encoded = await serializer.serialize("users", {"id": "u1"}, avro_schema)

        # Decode (schema fetched automatically from registry)
        decoded = await serializer.deserialize(encoded)
    """

    registry: SchemaRegistryClient
    subject_suffix: str = 'value'
    # Internal: cache (subject, schema_fingerprint) → schema_id
    _schema_id_cache: dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )

    async def serialize(self, topic: str, data: dict, schema: dict) -> bytes:
        """Serialize *data* to Avro bytes with the Confluent wire-format header.

        Registers the schema with the registry on first call for a given
        ``(topic, schema)`` pair; subsequent calls use the cached ID.

        Args:
            topic: Kafka topic name (used to derive the subject).
            data: Python dict to serialise.
            schema: Avro schema as a Python dict.

        Returns:
            Wire-format bytes (magic byte + schema_id + avro payload).
        """
        subject = f'{topic}-{self.subject_suffix}'
        schema_id = await self._get_or_register(subject, schema)

        parsed = fastavro.parse_schema(schema)
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed, data)
        return ConfluentWireFormat.encode(schema_id, buf.getvalue())

    async def deserialize(self, data: bytes) -> dict:
        """Deserialize Avro wire-format bytes to a Python dict.

        The schema is fetched from the registry using the embedded schema ID.

        Args:
            data: Wire-format bytes received from Kafka.

        Returns:
            Decoded Python dict.
        """
        schema_id, payload = ConfluentWireFormat.decode(data)
        schema = await self.registry.get_schema_by_id(schema_id)
        parsed = fastavro.parse_schema(schema)
        buf = io.BytesIO(payload)
        return fastavro.schemaless_reader(buf, parsed) # type: ignore

    async def _get_or_register(self, subject: str, schema: dict) -> int:
        """Return the schema ID, registering the schema if necessary."""
        fingerprint = f'{subject}:{json.dumps(schema, sort_keys=True)}'
        if fingerprint in self._schema_id_cache:
            return self._schema_id_cache[fingerprint]
        schema_id = await self.registry.register_schema(subject, schema)
        self._schema_id_cache[fingerprint] = schema_id
        return schema_id


# ---------------------------------------------------------------------------
# Avro data preparation helpers
# ---------------------------------------------------------------------------


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime string to an aware ``datetime`` object."""
    # Python 3.11+ fromisoformat handles 'Z' suffix; for older versions replace it.
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _prepare_for_avro(data: dict, schema: dict) -> dict:
    """
    Coerce ``data`` values so that they are compatible with the fastavro writer.

    Specifically:
    - Fields annotated with ``logicalType: timestamp-millis`` or
      ``timestamp-micros`` need a ``datetime`` (or integer), not an ISO string.
    - All other fields are passed through unchanged.
    """
    # Build a lookup from field name → Avro field definition
    field_defs: dict[str, Any] = {}
    for f in schema.get('fields', []):
        field_defs[f['name']] = f

    result: dict[str, Any] = {}
    for key, val in data.items():
        fdef = field_defs.get(key)
        if fdef is not None and isinstance(val, str):
            ftype = fdef.get('type', {})
            logical = (
                ftype.get('logicalType', '') if isinstance(ftype, dict) else ''
            )
            if logical in ('timestamp-millis', 'timestamp-micros'):
                try:
                    val = _parse_iso_datetime(val)
                except (ValueError, TypeError):
                    pass  # leave as-is; fastavro will raise a more informative error
        result[key] = val
    return result


# ---------------------------------------------------------------------------
# High-level async encoder (used by FastStreamKafkaMessagingService)
# ---------------------------------------------------------------------------


class SchemaRegistryEncoder(ISchemaRegistryEncoder):
    """
    A fast version of schema registry by using fastavro and httpx.

    This class wraps ``AvroSchemaRegistrySerializer`` and provides
    ``encode_event`` / ``decode`` methods compatible with the service's
    internal ``_encode_message`` / ``_decode_message`` helpers.

    Unlike the synchronous ``MsgEncoder``, this class requires ``await``
    because schema registration and lookup may involve HTTP round-trips.

    Args:
        registry_config: Schema Registry connection settings.
        avro_schemas: Mapping of ``topic_name → avro_schema_dict``.  The
            schema for a topic is registered with the registry on first use.

    Example::

        encoder = AsyncSchemaRegistryEncoder(
            registry_config=SchemaRegistryConfig(url="http://localhost:8081"),
            avro_schemas={
                "iam.users": {
                    "type": "record",
                    "name": "UserEvent",
                    "fields": [
                        {"name": "event_id", "type": "string"},
                        {"name": "event_type", "type": "string"},
                    ],
                }
            },
        )

        # In the messaging service:
        raw_bytes = await encoder.encode_event("iam.users", base_event)
        event = await encoder.decode("iam.users", raw_bytes)
    """

    def __init__(
        self,
        registry_config: SchemaRegistryConfig,
        avro_schemas: Optional[dict[str, dict]] = None,
    ) -> None:
        self._client = SchemaRegistryClient(registry_config)
        self._serializer = FastavroSerializer(self._client)
        self._avro_schemas: dict[str, dict] = avro_schemas or {}

    @property
    def logger(self):
        return LogFactory().get_logger(self.__class__.__name__)

    async def encode_event(self, topic: str, data: BaseSendableMessage) -> bytes:
        """Serialize *data* dict to Avro wire-format bytes.

        Args:
            topic: Kafka topic name — used for subject lookup and schema selection.
            data: Event data dict (typically from ``BaseEvent.as_dict()``).

        Returns:
            Confluent wire-format bytes.

        Raises:
            KeyError: When no Avro schema is registered for *topic*.
        """
        schema = self._get_schema(topic)
        prepared = _prepare_for_avro(data, schema) # type: ignore
        return await self._serializer.serialize(topic, prepared, schema)

    async def decode(self, topic: str, data: bytes) -> dict:
        """Deserialize Avro wire-format bytes to a Python dict.

        The Avro schema is looked up in the registry using the embedded
        schema ID, so no topic-specific schema configuration is needed
        on the decode path.

        Args:
            topic: Kafka topic name (unused at decode time, kept for API symmetry).
            data: Raw Kafka message bytes.

        Returns:
            Decoded Python dict.
        """
        return await self._serializer.deserialize(data)

    def register_topic_schema(self, topic: str, schema: dict) -> bool:
        """Register an Avro schema for *topic* at runtime.

        Useful when schemas are loaded dynamically from files or a config store.

        Args:
            topic: Kafka topic name.
            schema: Avro schema dict.
        """
        self._avro_schemas[topic] = schema

        self.logger.info(f'📚 Registered schema for channel "{topic}"')

        # Later should also register with the registry and cache the schema ID, but for now
        return True
        # return self._serializer.register_schema(topic, schema)

    @property
    def avro_schemas(self) -> dict[str, dict]:
        """Read-only view of the registered topic → Avro schema mapping."""
        return self._avro_schemas

    def _get_schema(self, topic: str) -> dict:
        """Return the Avro schema for *topic* or raise ``ValueError``."""
        if topic not in self._avro_schemas:
            raise ValueError(
                f"No Avro schema registered for topic '{topic}': "
                'no Avro schema found. '
                'Pass it via `avro_schemas` in the constructor or '
                'call `register_topic_schema(topic, schema)` first.'
            )
        return self._avro_schemas[topic]
