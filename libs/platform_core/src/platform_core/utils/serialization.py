import datetime
import json
from typing import Any
from uuid import UUID

import msgspec
from pydantic import BaseModel


def _default(value: Any) -> str:
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(by_alias=True))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime.datetime):
        return convert_datetime_to_gmt_iso(value)
    if isinstance(value, datetime.date):
        return convert_date_to_iso(value)
    try:
        val = str(value)
    except Exception as exc:
        raise TypeError from exc
    return val


_msgspec_json_encoder = msgspec.json.Encoder(enc_hook=_default)
_msgspec_json_decoder = msgspec.json.Decoder()


def to_json(value: Any) -> bytes:
    """Encode json with the optimized msgspec package.

    Returns:
        The json encoded bytes.
    """
    if isinstance(value, bytes):
        return value
    return _msgspec_json_encoder.encode(value)


def from_json(value: bytes | str) -> Any:
    """Decode to an object with the optimized msgspec package.

    Returns:
        The decoded object.
    """
    return _msgspec_json_decoder.decode(value)


def convert_datetime_to_gmt_iso(dt: datetime.datetime) -> str:
    """Handle datetime serialization for nested timestamps.

    Returns:
        The ISO formatted datetime string.

    Examples:
        >>> convert_datetime_to_gmt_iso(datetime.datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01T12:00:00Z'
    """
    dt = dt.replace(tzinfo=datetime.UTC) if not dt.tzinfo else dt.astimezone(datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def convert_datetime_to_utc_iso(dt: datetime.datetime) -> str:
    """Handle datetime serialization for nested timestamps.

    Returns:
        The ISO formatted datetime string.

    Examples:
        >>> convert_datetime_to_utc_iso(datetime.datetime(2024, 1, 1, 12, 0, 0))
        '2024-01-01T12:00:00Z'
    """
    dt = dt.replace(tzinfo=datetime.UTC) if not dt.tzinfo else dt.astimezone(datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def convert_date_to_iso(dt: datetime.date) -> str:
    """Handle date serialization for nested timestamps.

    Returns:
        The ISO formatted date string.

    Examples:
        >>> convert_date_to_iso(datetime.date(2024, 1, 1))
        '2024-01-01'
    """
    return dt.isoformat()
