"""
🗂️ Legacy Schema Registry implementation.

Adapter around `python-schema-registry-client`_ that conforms to the
interfaces defined in :mod:`core.messaging.schema_registry.types`, so it
can be used as a drop-in replacement for
:mod:`core.messaging.schema_registry.schema_registry_fast`.

The underlying ``schema_registry`` library is **synchronous**. To honour
the async protocols every blocking call is dispatched to a worker thread
via :func:`asyncio.to_thread`, which keeps the caller's event loop free.

.. _python-schema-registry-client: https://github.com/marcosschroh/python-schema-registry-client
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from platform_core.observability.log_factory import LogFactory

from .confluent import ConfluentWireFormat
from .sr_config import SchemaRegistryConfig
from .types import (
    ISchemaRegistryClient,
    ISchemaRegistryEncoder,
    ISchemaSerializer,
    SchemaNotFoundError,
    SchemaRegistryError,
)

# ---------------------------------------------------------------------------
# Lazy / optional imports
# ---------------------------------------------------------------------------
# The legacy client lives in an optional dependency. Import lazily so that
# environments that only use the fast encoder don't need to install it.
# Symbols are typed as ``Any`` because the library's own annotations are
# strict (e.g. ``BaseSchema`` instead of ``dict``) and would force callers
# to wrap every dict — defeating the protocol abstraction.
Auth: Any = None
_LibClient: Any = None
_LibMessageSerializer: Any = None
_LibAvroSchema: Any = None
_lib_available: bool = False

try:
    from httpx import BasicAuth as _ImportedAuth
    from schema_registry.client import (  # type: ignore[import-not-found]
        SchemaRegistryClient as _ImportedLibClient,
    )

    # from schema_registry.client.auth_utils import (  # type: ignore[import-not-found]
    #     Auth as _ImportedAuth,
    # )
    from schema_registry.client.schema import (  # type: ignore[import-not-found]
        AvroSchema as _ImportedAvroSchema,
    )
    from schema_registry.serializers.message_serializer import (  # type: ignore[import-not-found]
        AvroMessageSerializer as _ImportedLibMessageSerializer,
    )

    Auth = _ImportedAuth
    _LibClient = _ImportedLibClient
    _LibMessageSerializer = _ImportedLibMessageSerializer
    _LibAvroSchema = _ImportedAvroSchema
    _lib_available = True
except ImportError:  # pragma: no cover
    pass


def _ensure_available() -> None:
    if not _lib_available:
        raise ImportError(
            "The 'python-schema-registry-client' package is required for "
            'LegacySchemaRegistryEncoder. Install it with '
            "`pip install python-schema-registry-client`."
        )


def _wrap_lib_error(exc: BaseException) -> SchemaRegistryError:
    """Translate a library exception into our protocol-level error."""
    status = getattr(exc, 'status_code', None) or getattr(exc, 'http_code', None)
    msg = str(exc) or exc.__class__.__name__
    if status == 404:
        return SchemaNotFoundError(msg, status_code=status)
    return SchemaRegistryError(msg, status_code=status)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LegacySchemaRegistryClient(ISchemaRegistryClient):
    """``ISchemaRegistryClient`` backed by ``python-schema-registry-client``."""

    def __init__(self, config: SchemaRegistryConfig) -> None:
        _ensure_available()
        self._config = config
        auth = (
            Auth(username=config.username, password=config.password)
            if config.username and config.password
            else None
        )
        # ``timeout`` accepts ``httpx.Timeout`` in newer library versions; the
        # ``Any`` cast lets us pass a plain float without fighting the strict
        # library annotations.
        client_factory: Any = _LibClient
        self._client: Any = client_factory(
            url=config.url,
            auth=auth,
            timeout=config.timeout_seconds,
        )
        self._schema_by_id: dict[int, dict] = {}
        self._id_by_subject_fingerprint: dict[str, int] = {}

    # ------------------------------------------------------------------
    # ISchemaRegistryClient
    # ------------------------------------------------------------------

    async def register_schema(self, subject: str, schema: dict) -> int:
        fingerprint = f'{subject}:{json.dumps(schema, sort_keys=True)}'
        cached = self._id_by_subject_fingerprint.get(fingerprint)
        if cached is not None:
            return cached

        try:
            schema_id = await asyncio.to_thread(
                self._client.register, subject, _LibAvroSchema(schema)
            )
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc

        self._schema_by_id[int(schema_id)] = schema
        self._id_by_subject_fingerprint[fingerprint] = int(schema_id)
        return int(schema_id)

    async def get_schema_by_id(self, schema_id: int) -> dict:
        cached = self._schema_by_id.get(schema_id)
        if cached is not None:
            return cached

        try:
            result = await asyncio.to_thread(self._client.get_by_id, schema_id)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc

        if result is None:
            raise SchemaNotFoundError(f'Schema not found: id={schema_id}')

        schema = self._to_schema_dict(result)
        self._schema_by_id[schema_id] = schema
        return schema

    async def get_latest_schema(self, subject: str) -> tuple[int, dict]:
        try:
            result = await asyncio.to_thread(self._client.get_schema, subject)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc

        if result is None:
            raise SchemaNotFoundError(f'Subject not found: {subject!r}')

        schema_id = int(getattr(result, 'schema_id', 0))
        schema = self._to_schema_dict(getattr(result, 'schema', result))
        if schema_id:
            self._schema_by_id[schema_id] = schema
        return schema_id, schema

    async def subject_exists(self, subject: str) -> bool:
        try:
            result = await asyncio.to_thread(self._client.get_schema, subject)
            return result is not None
        except SchemaNotFoundError:
            return False
        except Exception as exc:  # noqa: BLE001
            wrapped = _wrap_lib_error(exc)
            if isinstance(wrapped, SchemaNotFoundError):
                return False
            raise wrapped from exc

    async def list_subjects(self) -> list[str]:
        try:
            return list(await asyncio.to_thread(self._client.get_subjects))
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc

    async def delete_subject(
        self, subject: str, *, permanent: bool = False
    ) -> list[int]:
        try:
            try:
                result = await asyncio.to_thread(
                    self._client.delete_subject, subject, permanent
                )
            except TypeError:
                # Older library versions don't accept the permanent flag.
                result = await asyncio.to_thread(
                    self._client.delete_subject, subject
                )
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc

        # Drop stale cache entries for this subject.
        self._id_by_subject_fingerprint = {
            k: v
            for k, v in self._id_by_subject_fingerprint.items()
            if not k.startswith(f'{subject}:')
        }
        return [int(v) for v in (result or [])]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def raw_client(self) -> Any:
        """Escape hatch: return the underlying library client."""
        return self._client

    @staticmethod
    def _to_schema_dict(value: Any) -> dict:
        """Coerce whatever the library returns into a plain dict."""
        if isinstance(value, dict):
            return value
        raw = getattr(value, 'raw_schema', None) or getattr(value, 'schema', None)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, str)):
            return json.loads(raw)
        return json.loads(str(value))


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


class LegacyAvroSerializer(ISchemaSerializer):
    """``ISchemaSerializer`` using ``schema_registry``'s ``MessageSerializer``.

    The library already produces / consumes the Confluent wire format, so
    we delegate to it directly. ``ConfluentWireFormat.decode`` is reused
    only to validate the framing on the decode path.
    """

    def __init__(
        self,
        client: LegacySchemaRegistryClient,
        *,
        subject_suffix: str = 'value',
    ) -> None:
        _ensure_available()
        self._client = client
        self._subject_suffix = subject_suffix
        serializer_factory: Any = _LibMessageSerializer
        self._serializer: Any = serializer_factory(
            schemaregistry_client=client.raw_client
        )

    async def serialize(self, topic: str, data: dict, schema: dict) -> bytes:
        subject = f'{topic}-{self._subject_suffix}'
        try:
            payload = await asyncio.to_thread(
                self._serializer.encode_record_with_schema,
                subject,
                _LibAvroSchema(schema),
                data,
            )
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc
        return bytes(payload)

    async def deserialize(self, data: bytes) -> dict:
        # Validate the wire format eagerly so we surface a consistent error type.
        ConfluentWireFormat.decode(data)
        try:
            decoded = await asyncio.to_thread(self._serializer.decode_message, data)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_lib_error(exc) from exc
        if isinstance(decoded, dict):
            return decoded
        # decode_message can return any avro-compatible value; coerce to dict.
        return dict(decoded) if decoded is not None else {}


# ---------------------------------------------------------------------------
# High-level encoder
# ---------------------------------------------------------------------------


class LegacySchemaRegistryEncoder(ISchemaRegistryEncoder):
    """Drop-in replacement for ``AsyncSchemaRegistryEncoder``.

    Same public surface (``encode_event`` / ``decode`` /
    ``register_topic_schema`` / ``avro_schemas``) but powered by the legacy
    ``python-schema-registry-client`` library. Switch implementations by
    swapping the concrete class — every call site that depends on
    :class:`ISchemaRegistryEncoder` keeps working unchanged.
    """

    def __init__(
        self,
        registry_config: SchemaRegistryConfig,
        avro_schemas: Optional[dict[str, dict]] = None,
        *,
        subject_suffix: str = 'value',
    ) -> None:
        self._client = LegacySchemaRegistryClient(registry_config)
        self._serializer = LegacyAvroSerializer(
            self._client, subject_suffix=subject_suffix
        )
        self._avro_schemas: dict[str, dict] = dict(avro_schemas or {})

    @property
    def logger(self):
        return LogFactory().get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # ISchemaRegistryEncoder
    # ------------------------------------------------------------------

    async def encode_event(self, topic: str, data: dict) -> bytes:
        schema = self._get_schema(topic)
        return await self._serializer.serialize(topic, data, schema)

    async def decode(self, topic: str, data: bytes) -> dict:
        return await self._serializer.deserialize(data)

    def register_topic_schema(self, topic: str, schema: dict) -> str:
        """Cache *schema* for *topic*. Registration with the registry is lazy
        (happens on the first ``encode_event`` call), matching the behaviour
        of :class:`AsyncSchemaRegistryEncoder`.
        """
        self._avro_schemas[topic] = schema
        self.logger.info(f'📚 Registered schema for channel "{topic}" (legacy)')
        return ''

    @property
    def avro_schemas(self) -> dict[str, dict]:
        return self._avro_schemas

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_schema(self, topic: str) -> dict:
        if topic not in self._avro_schemas:
            raise ValueError(
                f"No Avro schema registered for topic '{topic}': "
                'pass it via `avro_schemas` in the constructor or call '
                '`register_topic_schema(topic, schema)` first.'
            )
        return self._avro_schemas[topic]

