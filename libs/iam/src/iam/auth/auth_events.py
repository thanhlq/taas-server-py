"""
Typed flat IAM event classes (Option 2 — flat AvroModel inheritance).

Each class merges metadata fields (inherited from ``BaseEvent``) with its own
domain-specific payload fields into a single flat dataclass.  This enables:

  * Native Avro schema generation via ``AvroModel`` (call ``.avro_schema_to_python()``)
  * Clean schema registration in Confluent Schema Registry
  * Direct field access without an extra envelope unwrap step

Wire format produced by ``event.as_dict()``::

    {
        "event_type": "user.registered",
        "event_id": "...",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "retry_count": 0,
        "source": null,
        "correlation_id": null,
        "user_id": "...",    # the registered user's ID
        "handler_name": null,
        "email": "user@example.com",
        "username": "user@example.com",
        "realm_name": "acme",
        "tenant_id": "...",
        "user": "{\\"id\\":\\"...\\",...}",    # JSON-serialised user dict
        "tenant": "{\\"id\\":\\"...\\",...}"   # JSON-serialised tenant dict
    }
"""

# NOTE: ``BaseEvent`` is a ``msgspec.Struct`` (not a dataclass), so field
# defaults must use ``msgspec.field`` — ``dataclasses.field`` would be stored
# verbatim as the literal default (a ``Field`` object), breaking serialization.
from typing import Any

from foundation.messaging.types import BaseEvent
from foundation.serialization import BaseEventPayload
from msgspec import field

from iam.auth.types import DirectoryTenant, DirectoryUser
from iam.iam_constants import IamEvents

# ---------------------------------------------------------------------------
# Tenant events
# ---------------------------------------------------------------------------


class TenantCreatedEvent(BaseEvent, kw_only=True):
    """Fired when a new tenant is created."""

    event_type: str = field(default=IamEvents.TENANT_CREATED)

    tenant_id: str | None = field(default='')
    root_account_id: str | None = field(default='')


# ---------------------------------------------------------------------------
# User directory / registration events
# ---------------------------------------------------------------------------


class UserDirectoryEventPayload(BaseEventPayload):
    user: DirectoryUser
    tenant: DirectoryTenant


class UserDirectoryCreatedEvent(BaseEvent[UserDirectoryEventPayload]):
    """
    Fired when a user is created in the identity directory (e.g. Keycloak).

    ``user`` and ``tenant`` are stored as JSON strings so that the Avro
    schema remains clean (Avro has no native ``map`` type with arbitrary keys).
    Use ``get_user_dict()`` / ``get_tenant_dict()`` to deserialise them.
    """

    event_type: str = field(default=IamEvents.USER_DIRECTORY_CREATED)
    # Override base user_id with the directory user's ID (non-nullable once set)
    # user_id: str = ""
    email: str = ''
    username: str = ''
    realm_name: str = ''
    # tenant_id: str = ''

    # user: Optional[str] = None  # JSON-serialised user dict
    # tenant: bytes | str | None = None
    """
    bytes: Avro-encoded bytes (if using Avro serialization) or msgpack-encoded bytes (if using msgpack serialization)
    str: JSON-serialised dict (if using JSON serialization)
    dict: Already deserialised dict (if accessed programmatically after deserialization)
    None: Not set
    """

    @property
    def user(self) -> DirectoryUser:
        """Get the directory user as a deserialised dict."""
        _payload: Any = self.payload
        if isinstance(_payload, UserDirectoryEventPayload):
            return _payload.user
        elif isinstance(_payload, dict):
            return DirectoryUser(**_payload.get('user', {}))
        else:
            raise ValueError('Invalid payload type for user')

    @property
    def tenant(self) -> DirectoryTenant:
        """Get the directory tenant as a deserialised dict."""
        _payload: Any = self.payload
        if isinstance(_payload, UserDirectoryEventPayload):
            return _payload.tenant
        elif isinstance(_payload, dict):
            return DirectoryTenant(**_payload.get('tenant', {}))
        else:
            raise ValueError('Invalid payload type for tenant')


class UserRegisteredEvent(UserDirectoryCreatedEvent):
    """
    Fired when user registration is fully persisted in the internal DB.

    Inherits all fields from ``UserDirectoryCreatedEvent`` and only overrides
    ``event_type``.
    """

    event_type: str = field(default=IamEvents.USER_REGISTERED)
