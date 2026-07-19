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
from dataclasses import field

from foundation.messaging.types import BaseEvent
from foundation.serialization import BaseEventPayload

from iam.auth.types import DirectoryTenant, DirectoryUser
from iam.iam_constants import IamEvents

# ---------------------------------------------------------------------------
# Tenant events
# ---------------------------------------------------------------------------

class TenantCreatedEvent(BaseEvent):
    """Fired when a new tenant is created."""

    event_type: str = field(default=IamEvents.TENANT_CREATED)

    root_account_id: str = ''
    # root_account: bytes | str | None = None

    # def get_root_account_dict(self) -> dict[str, Any] | None:
    #     return self.payload_as_dict(self.root_account)

    # def get_root_account(self) -> User | None:
    #     """Return the deserialised root-account as a User object, or ``None`` if not set."""
    #     root_account_dict = self.get_root_account_dict()
    #     if root_account_dict is None:
    #         return None
    #     return User(**root_account_dict)


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

    # def get_user_dict(self) -> dict[str, Any]:
    #     user: dict[str, Any] = self.payload_as_dict().get('user')  # type: ignore
    #     return user

    # def get_tenant_dict(self) -> dict[str, Any]:
    #     tenant: dict[str, Any] = self.payload_as_dict().get('tenant')  # type: ignore
    #     return tenant

    # def get_user(self) -> UserEntity:
    #     # """Return the deserialised user as a User object, or ``None`` if not set."""
    #     # user_dict = self.get_user_dict()
    #     # if user_dict is None:
    #     #     return None
    #     # return User(**user_dict)
    #     user: dict[str, Any] = self.payload_as_dict().get('user')  # type: ignore
    #     return UserEntity(**user)

    # def get_tenant(self) -> Tenant:
    #     # """Return the deserialised tenant as a Tenant object, or ``None`` if not set."""
    #     # tenant_dict = self.get_tenant_dict()
    #     # if tenant_dict is None:
    #     #     return None
    #     # return Tenant(**tenant_dict)
    #     tenant: dict[str, Any] = self.payload_as_dict().get('tenant')  # type: ignore
    #     return Tenant(**tenant)


class UserRegisteredEvent(UserDirectoryCreatedEvent):
    """
    Fired when user registration is fully persisted in the internal DB.

    Inherits all fields from ``UserDirectoryCreatedEvent`` and only overrides
    ``event_type``.
    """

    event_type: str = field(default=IamEvents.USER_REGISTERED)
