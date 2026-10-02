"""
Base and column types of the ``resiliant_*`` models.

The tables are created by the drizzle migrations shared with taas-server-js
(``resiliant.migrations``); these models map them column for column — the
``db`` consistency check fails at startup on any difference, in both directions.
Conventions (same as ``@taas/resiliant``):

* ids are ``bigint`` identities (``GENERATED ALWAYS``) — monotonic, so claim order is id order;
* enumerations are ``text`` + CHECK (never pg enums), mapped by :class:`EnumText`;
* payloads are ``jsonb``; timestamps ``timestamptz``, set from the database clock
  (``func.now()``) wherever a relay or poller depends on them.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from advanced_alchemy.base import AdvancedDeclarativeBase
from sqlalchemy import BigInteger, DateTime, Identity, Text, TypeDecorator, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

Timestamptz = DateTime(timezone=True)
Jsonb = JSONB


class EnumText[E: enum.Enum](TypeDecorator[Any]):
    """A ``text`` column holding the *values* of a ``StrEnum`` (``'pending'``, not ``'PENDING'``).

    Unknown values read back as plain strings: the Node relay of the same table
    may use a status / target this process does not know.
    """

    impl = Text
    cache_ok = True

    def __init__(self, enum_cls: type[E]) -> None:
        super().__init__()
        self.enum_cls = enum_cls

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return value.value if isinstance(value, enum.Enum) else str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        try:
            return self.enum_cls(value)
        except ValueError:
            return value


def bigint_identity_pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(Timestamptz, nullable=False, server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        Timestamptz, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ResiliantBase(AdvancedDeclarativeBase):
    """Abstract base of every resiliant model (advanced_alchemy's shared registry)."""

    __abstract__ = True

    def as_dict(self) -> dict[str, Any]:
        """Every column by attribute name; timestamps as ISO strings, enums as values."""
        result: dict[str, Any] = {}
        for attr in self.__mapper__.column_attrs:  # type: ignore[attr-defined]
            value = getattr(self, attr.key)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, enum.Enum):
                value = value.value
            result[attr.key] = value
        return result


__all__ = [
    'EnumText',
    'Jsonb',
    'ResiliantBase',
    'Timestamptz',
    'bigint_identity_pk',
    'created_at_column',
    'updated_at_column',
]
