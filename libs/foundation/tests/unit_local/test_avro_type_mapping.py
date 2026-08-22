"""Avro schema generation from ``msgspec.Struct`` annotations.

Regression cover for ``TypeError: must be string on field source`` — an
``Optional[str]`` field was emitted as a required Avro ``"string"``, so any
event with an unset optional field failed to encode.
"""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import io
import logging
import uuid
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


# ---------------------------------------------------------------------------
# Per-record subjects + field-loss guard
#
# Regression cover for silent data loss: several event types share one Kafka
# topic (7 map to iam.user.registered, 9 to iam.auth), and registering a single
# schema per topic encoded all but one of them with a sibling's schema.
# fastavro drops unknown dict keys, so the publish "succeeded" while fields
# went missing — the consumer saw `tenant ID: undefined`.
# ---------------------------------------------------------------------------


class _EventA(msgspec.Struct):
    event_type: str = 'a.happened'
    shared: str = ''
    only_on_a: str = ''


class _EventB(msgspec.Struct):
    event_type: str = 'b.happened'
    shared: str = ''
    only_on_b: str = ''


def _encoder():
    from foundation.messaging.kafka.sr.schema_registry_fast import SchemaRegistryEncoder
    from foundation.messaging.kafka.sr.sr_config import SchemaRegistryConfig

    return SchemaRegistryEncoder(SchemaRegistryConfig(url='http://unused.invalid:8081'))


def test_sibling_event_types_on_one_topic_keep_their_own_schema() -> None:
    enc = _encoder()
    enc.register_topic_schema('t', to_avro(_EventA), event_type='a.happened')
    enc.register_topic_schema('t', to_avro(_EventB), event_type='b.happened')

    assert enc._get_schema('t', 'a.happened')['name'] == '_EventA'
    assert enc._get_schema('t', 'b.happened')['name'] == '_EventB'


def test_unknown_event_type_falls_back_to_topic_schema() -> None:
    """Topics carrying a single type must keep working without event_type."""
    enc = _encoder()
    enc.register_topic_schema('t', to_avro(_EventA), event_type='a.happened')

    assert enc._get_schema('t', 'never.registered')['name'] == '_EventA'
    assert enc._get_schema('t')['name'] == '_EventA'


def test_missing_topic_still_raises() -> None:
    enc = _encoder()
    with pytest.raises(ValueError, match='No Avro schema registered'):
        enc._get_schema('absent', 'a.happened')


def test_guard_rejects_fields_the_schema_would_drop() -> None:
    from foundation.messaging.kafka.sr.schema_registry_fast import (
        AvroFieldLossError,
        _assert_no_field_loss,
    )

    data = {'event_type': 'b.happened', 'shared': 'x', 'only_on_b': 'lost!'}
    with pytest.raises(AvroFieldLossError) as exc:
        _assert_no_field_loss(
            data, to_avro(_EventA), topic='t', event_type='b.happened'
        )
    assert 'only_on_b' in str(exc.value)


def test_guard_allows_missing_fields_that_have_defaults() -> None:
    """Absent fields are fine — Avro fills them from the schema default."""
    from foundation.messaging.kafka.sr.schema_registry_fast import _assert_no_field_loss

    _assert_no_field_loss(
        {'event_type': 'a.happened'}, to_avro(_EventA), topic='t', event_type='a.happened'
    )


def test_registration_covers_every_event_class_not_one_per_topic() -> None:
    from foundation.messaging.events.flow_registration import (
        topic_event_schema_pairs,
        topic_to_schema_event,
    )

    class _Step:
        def __init__(self, event, emits=()):
            self.event = event
            self.emits = tuple(emits)

    flows = {'f': (_Step(_EventA, [_EventB]),)}
    topic_for = lambda cls: 'shared.topic'  # noqa: E731

    pairs = topic_event_schema_pairs(flows, topic_for)
    assert sorted(c.__name__ for _, c in pairs) == ['_EventA', '_EventB']
    # The old helper collapses to one, which is exactly the bug it caused.
    assert len(topic_to_schema_event(flows, topic_for)) == 1


# ---------------------------------------------------------------------------
# Exact-value types
#
# A crypto/financial payload must never be silently rounded or reshaped. These
# lock in that Decimal is carried as an exact string rather than a float, and
# that any annotation we cannot map is at least reported.
# ---------------------------------------------------------------------------


class _Money(msgspec.Struct):
    amount: decimal.Decimal
    account: uuid.UUID
    maybe_fee: decimal.Decimal | None = None


def test_decimal_is_exact_string_never_float() -> None:
    schema = to_avro(_Money)
    assert _field(schema, 'amount')['type'] == 'string'
    assert _field(schema, 'account')['type'] == 'string'
    assert _field(schema, 'maybe_fee')['type'] == ['null', 'string']


def test_decimal_round_trips_without_precision_loss() -> None:
    schema = to_avro(_Money)
    parsed = fastavro.parse_schema(schema)
    # A value that float64 cannot represent exactly.
    amount = decimal.Decimal('12345678901234567890.123456789')

    buf = io.BytesIO()
    fastavro.schemaless_writer(
        buf, parsed, {'amount': str(amount), 'account': str(uuid.uuid4()), 'maybe_fee': None}
    )
    buf.seek(0)
    decoded = fastavro.schemaless_reader(buf, parsed)

    assert decimal.Decimal(decoded['amount']) == amount


class _Opaque:
    """A type the mapper has no rule for."""


class _HasOpaque(msgspec.Struct):
    weird: _Opaque


def test_unmappable_annotation_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(
        logging.WARNING, logger='foundation.messaging.kafka.sr.serializer'
    ):
        schema = to_avro(_HasOpaque)

    assert _field(schema, 'weird')['type'] == 'string'
    assert any('No Avro mapping' in r.message for r in caplog.records)
