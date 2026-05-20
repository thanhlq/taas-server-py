from typing import Any

import msgspec

class BaseModel(msgspec.Struct, omit_defaults=True):
    def as_dict(self) -> dict[str, Any]:
        # Round-trip through msgspec: fast C path, drops UNSET via omit_defaults.
        return msgspec.to_builtins(self)

    def as_json(self) -> str:
        return msgspec.json.encode(self).decode()

    def as_json_bytes(self) -> bytes:
        return msgspec.json.encode(self)


class ApiResponse(BaseModel, rename="camel"):
    """Camelized Base Struct"""


# class Message(CamelizedBaseStruct):
#     message: str
