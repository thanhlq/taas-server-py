from typing import Any

import msgspec


class BaseModel(msgspec.Struct, omit_defaults=True):
    """ Base model for serialization/deserialization using msgspec."""

    def as_dict(self) -> dict[str, Any]:
        # Round-trip through msgspec: fast C path, drops UNSET via omit_defaults.
        return msgspec.to_builtins(self)

    def as_json(self) -> str:
        return msgspec.json.encode(self).decode()

    def as_json_bytes(self) -> bytes:
        return msgspec.json.encode(self)

class BaseEvent(msgspec.Struct, omit_defaults=True):
    """Base class for event payloads."""

    def as_dict(self) -> dict[str, Any]:
        # Round-trip through msgspec: fast C path, drops UNSET via omit_defaults.
        return msgspec.to_builtins(self)

    def as_json(self) -> str:
        return msgspec.json.encode(self).decode()

    def as_json_bytes(self) -> bytes:
        return msgspec.json.encode(self)

class BaseEventPayload(msgspec.Struct, omit_defaults=True):
    """Base class for event payloads."""

    def as_dict(self) -> dict[str, Any]:
        # Round-trip through msgspec: fast C path, drops UNSET via omit_defaults.
        return msgspec.to_builtins(self)

    def as_json(self) -> str:
        return msgspec.json.encode(self).decode()

    def as_json_bytes(self) -> bytes:
        return msgspec.json.encode(self)

# , rename='camel'
class ApiResponse(BaseModel):
    """Camelized Base Struct"""

class CamelizedBaseStruct(BaseModel):
    """Camelized Base Struct"""


class ApiRequest(BaseModel):
    """
    Accept camel case from browser (client api), but convert to snake case for internal processing.
    This is useful for cases where we want to use the same schema for both request and response,
    but want to have different naming conventions for the client and server.

    For examples:
    class CreateUserRequest(ApiRequest):
        first_name: str
        last_name: str

    """

class PagingQueryParam(ApiRequest):
    limit: int = 25
    offset: int = 0

# class Message(CamelizedBaseStruct):
#     message: str
