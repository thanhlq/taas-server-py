from dataclasses import dataclass
from typing import Any, Callable

from advanced_alchemy.config import EngineConfig as _EngineConfig
from platform_core.serialization import encode_json
from platform_core.serialization._msgspec_hooks import decode_json
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

type DBAsyncScopedSession = async_scoped_session[AsyncSession]
type DBAsyncSession = AsyncSession

# @dataclass
# class EngineConfig(_EngineConfig):
#     """Configuration for SQLAlchemy's :class:`Engine <sqlalchemy.engine.Engine>`.

#     For details see: https://docs.sqlalchemy.org/en/20/core/engines.html
#     """

#     json_deserializer: Callable[[str], Any] = decode_json
#     """For dialects that support the :class:`JSON <sqlalchemy.types.JSON>` datatype, this is a Python callable that will
#     convert a JSON string to a Python object. By default, this is set to Litestar's decode_json function."""
#     json_serializer: Callable[[Any], str] = encode_json
#     """For dialects that support the JSON datatype, this is a Python callable that will render a given object as JSON.
#     By default, Litestar's encode_json function is used."""


class DBSessionStats:
    """
    A class to track statistics about database sessions.
    """

    def __init__(self):
        self.total_sessions_created: int = 0
        self.total_sessions_closed: int = 0
        self.total_sessions_committed: int = 0
        self.total_sessions_rolled_back: int = 0

    def increment_created(self, count: int = 1):
        self.total_sessions_created += count

    def increment_closed(self, count: int = 1):
        self.total_sessions_closed += count

    def increment_committed(self, count: int = 1):
        self.total_sessions_committed += count

    def increment_rolled_back(self, count: int = 1):
        self.total_sessions_rolled_back += count
