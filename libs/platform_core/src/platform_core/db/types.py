from dataclasses import dataclass
from typing import Any, Callable

from advanced_alchemy.config import EngineConfig as _EngineConfig

from platform_core.serialization._msgspec_hooks import decode_json

@dataclass
class EngineConfig(_EngineConfig):
    """Configuration for SQLAlchemy's :class:`Engine <sqlalchemy.engine.Engine>`.

    For details see: https://docs.sqlalchemy.org/en/20/core/engines.html
    """

    json_deserializer: Callable[[str], Any] = decode_json
    """For dialects that support the :class:`JSON <sqlalchemy.types.JSON>` datatype, this is a Python callable that will
    convert a JSON string to a Python object. By default, this is set to Litestar's decode_json function."""
    json_serializer: Callable[[Any], str] = serializer
    """For dialects that support the JSON datatype, this is a Python callable that will render a given object as JSON.
    By default, Litestar's encode_json function is used."""
