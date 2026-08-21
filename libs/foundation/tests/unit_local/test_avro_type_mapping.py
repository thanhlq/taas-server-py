"""Avro schema generation from ``msgspec.Struct`` annotations.

Regression cover for ``TypeError: must be string on field source`` — an
``Optional[str]`` field was emitted as a required Avro ``"string"``, so any
event with an unset optional field failed to encode.
"""

from __future__ import annotations

import datetime as dt
import enum
import io
from typing import Optional

import fastavro
import msgspec
import pytest

from foundation.messaging.kafka.sr.serializer import (
    _convert_msgspec_struct_to_avro_schema as to_avro,
)


def _field(schema: dict, name: str) -> dict:
    return next(f for f in schema['fields'] if f['name'] == name)


class _Scalars(msgspec.Struct):
    s: str
    i: int
    f: float
    b: bool
    raw: bytes


def test_scalars_map_to_widest_avro_form() -> None:
    """Python int/float are unbounded/double — narrow Avro forms would truncate."""
    schema = to_avro(_Scalars)
    assert _field(schema, 's')['type'] == 'string'
    assert _field(schema, 'i')['type'] == 'long'
    assert _field(schema, 'f')['type'] == 'double'
    assert _field(schema, 'b')['type'] == 'boolean'
    assert _field(schema, 'raw')['type'] == 'bytes'


class _Optionals(msgspec.Struct):
    source: Optional[str] = None
    pipe_style: str | None = None
    multi: bytes | str | dict | None = None


def test_optional_becomes_nullable_union_with_null_default() -> None:
    schema = to_avro(_Optionals)

    source = _field(schema, 'source')
    assert source['type'] == ['null', 'string']
    assert source['default'] is None

    # PEP 604 spelling must behave identically to typing.Optional.
    assert _field(schema, 'pipe_style')['type'] == ['null', 'string']

    multi = _field(schema, 'multi')
    assert multi['type'][0] == 'null', 'null must lead so the default is legal'
    assert 'bytes' in multi['type'] and 'string' in multi['type']
    assert multi['default'] is None


def test_none_unset_optional_actually_encodes() -> None:
    """The exact failure mode: an unset optional field must serialize."""
    schema = to_avro(_Optionals)
    parsed = fastavro.parse_schema(schema)
    buf = io.BytesIO()

    fastavro.schemaless_writer(
        buf, parsed, {'source': None, 'pipe_style': None, 'multi': None}
    )

    buf.seek(0)
    assert fastavro.schemaless_reader(buf, parsed)['source'] is None


class _Temporal(msgspec.Struct):
    at: dt.datetime
    day: dt.date


def test_datetime_maps_to_logical_type() -> None:
    """Must be a logical type: ``_prepare_for_avro`` keys its ISO-string
    coercion off ``logicalType``, which is what lets the outbox path work."""
    schema = to_avro(_Temporal)
    assert _field(schema, 'at')['type'] == {
        'type': 'long',
        'logicalType': 'timestamp-micros',
    }
    assert _field(schema, 'day')['type']['logicalType'] == 'date'


def test_datetime_round_trips_as_datetime() -> None:
    schema = to_avro(_Temporal)
    parsed = fastavro.parse_schema(schema)
    now = dt.datetime(2026, 8, 21, 12, 30, tzinfo=dt.UTC)

    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, {'at': now, 'day': now.date()})
    buf.seek(0)
    decoded = fastavro.schemaless_reader(buf, parsed)

    assert decoded['at'] == now


class _Colour(enum.Enum):
    RED = 'red'
    BLUE = 'blue'


class _Nested(msgspec.Struct):
    name: str


class _Containers(msgspec.Struct):
    tags: list[str]
    counts: dict[str, int]
    bare_list: list
    child: _Nested
    colour: _Colour


def test_containers_and_nested_types() -> None:
    schema = to_avro(_Containers)
    assert _field(schema, 'tags')['type'] == {'type': 'array', 'items': 'string'}
    assert _field(schema, 'counts')['type'] == {'type': 'map', 'values': 'long'}
    assert _field(schema, 'bare_list')['type']['type'] == 'array'

    child = _field(schema, 'child')['type']
    assert child['type'] == 'record' and child['name'] == '_Nested'
    assert _field(schema, 'colour')['type']['symbols'] == ['RED', 'BLUE']


class _Twice(msgspec.Struct):
    a: _Nested
    b: _Nested


def test_repeated_struct_is_referenced_not_redefined() -> None:
    """Avro rejects defining a named type twice in one schema."""
    schema = to_avro(_Twice)
    assert _field(schema, 'a')['type']['type'] == 'record'
    assert _field(schema, 'b')['type'] == '_Nested'
    fastavro.parse_schema(schema)  # would raise on redefinition


class _Defaults(msgspec.Struct):
    required: str
    retry_count: int = 0
    label: str = 'x'
    made: dt.datetime = msgspec.field(default_factory=lambda: dt.datetime.now())


def test_static_defaults_emitted_dynamic_ones_skipped() -> None:
    schema = to_avro(_Defaults)
    assert 'default' not in _field(schema, 'required')
    assert _field(schema, 'retry_count')['default'] == 0
    assert _field(schema, 'label')['default'] == 'x'
    # A default_factory value cannot be expressed in a static schema.
    assert 'default' not in _field(schema, 'made')


@pytest.mark.parametrize(
    'struct',
    [_Scalars, _Optionals, _Temporal, _Containers, _Twice, _Defaults],
)
def test_every_generated_schema_is_valid_avro(struct: type[msgspec.Struct]) -> None:
    fastavro.parse_schema(to_avro(struct))
