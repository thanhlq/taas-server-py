from foundation.utils.dt_utils import (
    convert_datetime_to_gmt_iso,
    convert_date_to_iso,
)
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
