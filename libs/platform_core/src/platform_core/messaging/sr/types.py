"""
🧩 Schema Registry — abstract interfaces.

This module defines the *contract* every Schema Registry implementation
(Confluent, Apicurio, AWS Glue, in-memory mock, …) must satisfy. The
concrete implementations live in sibling modules (e.g.
``schema_registry_fast.py``).

Design notes
------------
* ``Protocol`` is used instead of ``ABC`` so implementations don't need to
  inherit from these types — they only need to match the structural shape.
  This keeps third-party / mock implementations frictionless.
* Each layer of the stack has its own protocol so callers can depend only
  on what they actually use:

  - ``IWireFormat``        — magic-byte / schema-id framing
  - ``ISchemaRegistryClient`` — REST-style schema CRUD
  - ``ISchemaSerializer``  — bytes ↔ dict using a registry + wire format
  - ``ISchemaRegistryEncoder`` — high-level facade used by messaging services

* Common error types live here so callers can ``except`` them regardless
  of the underlying implementation.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SchemaRegistryError(Exception):
    """Base class for any Schema Registry failure."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SchemaNotFoundError(SchemaRegistryError):
    """Raised when a schema/subject is not found in the registry."""


class WireFormatError(SchemaRegistryError):
    """Raised when an incoming payload does not match the expected wire format."""


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------


@runtime_checkable
class IWireFormat(Protocol):
    """Frame / unframe a payload with a schema identifier.

    Implementations decide the on-wire layout (Confluent's 1+4 byte header,
    Apicurio's globalId header, etc.).
    """

    def encode(self, schema_id: int, payload: bytes) -> bytes:
        """Wrap *payload* with a header carrying *schema_id*."""
        ...

    def decode(self, data: bytes) -> tuple[int, bytes]:
        """Return ``(schema_id, payload)`` extracted from *data*.

        Raises:
            WireFormatError: When *data* doesn't conform to the expected layout.
        """
        ...


# ---------------------------------------------------------------------------
# Registry client (low-level CRUD)
# ---------------------------------------------------------------------------


@runtime_checkable
class ISchemaRegistryClient(Protocol):
    """Async CRUD client for a Schema Registry backend."""

    async def register_schema(self, subject: str, schema: dict) -> int:
        """Register *schema* under *subject*; return the assigned schema ID."""
        ...

    async def get_schema_by_id(self, schema_id: int) -> dict:
        """Fetch the schema dict for *schema_id*.

        Raises:
            SchemaNotFoundError: When no such schema exists.
        """
        ...

    async def get_latest_schema(self, subject: str) -> tuple[int, dict]:
        """Return ``(schema_id, schema)`` for the latest version of *subject*.

        Raises:
            SchemaNotFoundError: When the subject has no registered versions.
        """
        ...

    async def subject_exists(self, subject: str) -> bool:
        """Return ``True`` iff *subject* has at least one registered schema."""
        ...

    async def list_subjects(self) -> list[str]:
        """Return all subjects known to the registry."""
        ...

    async def delete_subject(
        self, subject: str, *, permanent: bool = False
    ) -> list[int]:
        """Delete every version of *subject*; return the deleted version numbers."""
        ...


# ---------------------------------------------------------------------------
# Serializer (bytes ↔ dict, knows about wire format + registry)
# ---------------------------------------------------------------------------


@runtime_checkable
class ISchemaSerializer(Protocol):
    """Encode / decode a Python dict using a registry-managed schema."""

    async def serialize(self, topic: str, data: dict, schema: dict) -> bytes:
        """Serialise *data* against *schema* into wire-format bytes for *topic*."""
        ...

    async def deserialize(self, data: bytes) -> dict:
        """Reverse of :meth:`serialize`. Schema is resolved from the embedded ID."""
        ...


# ---------------------------------------------------------------------------
# High-level encoder (facade used by the messaging service)
# ---------------------------------------------------------------------------


@runtime_checkable
class ISchemaRegistryEncoder(Protocol):
    """High-level facade exposed to ``IMessagingService`` implementations.

    Concrete encoders own a registry client + serializer and maintain a
    ``topic → schema`` map so the messaging layer doesn't need to.
    """

    async def encode_event(self, topic: str, data: dict) -> bytes:
        """Serialise *data* (typically ``BaseEvent.as_dict()``) for *topic*."""
        ...

    async def decode(self, topic: str, data: bytes) -> dict:
        """Deserialise *data* received on *topic* back to a Python dict."""
        ...

    def register_topic_schema(self, topic: str, schema: dict) -> Any:
        """Associate *schema* with *topic* (and optionally pre-register it).

        Return value is implementation-defined (e.g. schema ID, ack token,
        empty string for lazy registration).
        """
        ...

    @property
    def avro_schemas(self) -> dict[str, dict]:
        """Read-only view of registered ``topic → schema`` mappings."""
        ...
