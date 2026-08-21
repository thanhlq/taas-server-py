import datetime as _dt
import types as _types
import typing
from typing import Any, Union

import msgspec
from foundation.utils.predicates import is_dataclass_class
from ...types import BaseEvent


def schema_cls_to_avro_schema(
    schema_cls: type[BaseEvent | msgspec.Struct | Any],
) -> dict:
    """
    Convert a dataclass to an Avro schema dictionary.

    Args:
        schema_cls (type[BaseEvent]): The dataclass type to convert.

    Returns:
        dict: The Avro schema as a dictionary.
    """
    if not issubclass(schema_cls, BaseEvent):
        raise ValueError(
            f'Provided schema_cls {schema_cls.__name__} is not a subclass of BaseEvent.'
        )

    # If dataclass, convert to Avro schema using dataclasses_avroschema
    if is_dataclass_class(schema_cls):
        from dataclasses_avroschema import AvroModel

        if not issubclass(schema_cls, AvroModel):
            raise ValueError(
                f'Provided schema_cls {schema_cls.__name__} is not a subclass of AvroModel.'
            )

        return schema_cls.avro_schema_to_python()
    elif issubclass(schema_cls, msgspec.Struct):
        return _convert_msgspec_struct_to_avro_schema(schema_cls)
    else:
        raise ValueError(
            f'Provided schema_cls {schema_cls.__name__} is neither a dataclass nor a msgspec.Struct.'
        )


def _convert_msgspec_struct_to_avro_schema(schema_cls: type[msgspec.Struct]) -> dict:
    """
    Convert a msgspec.Struct to an Avro schema dictionary.

    Args:
        schema_cls (type[msgspec.Struct]): The msgspec.Struct type to convert.

    Returns:
        dict: The Avro schema as a dictionary.
    """
    return _record_schema(schema_cls, defined={})


# ---------------------------------------------------------------------------
# msgspec annotation → Avro type mapping
# ---------------------------------------------------------------------------

# Scalars. Python ``int`` is unbounded and ``float`` is a C double, so they map
# to Avro's 64-bit forms — 'int'/'float' would silently truncate. Avro promotes
# int→long and float→double on read, so widening stays reader-compatible.
_SCALAR_AVRO_TYPES: dict[Any, Any] = {
    bool: 'boolean',  # before int: bool is a subclass of int
    int: 'long',
    float: 'double',
    str: 'string',
    bytes: 'bytes',
    type(None): 'null',
}

# ``_prepare_for_avro`` parses ISO strings into datetimes for exactly these
# logical types, so declaring them here is what activates that coercion and
# lets both publish paths work: the direct path passes a real ``datetime``,
# while the outbox path passes the ISO string its JSON round-trip produced.
_LOGICAL_AVRO_TYPES: dict[Any, Any] = {
    _dt.datetime: {'type': 'long', 'logicalType': 'timestamp-micros'},
    _dt.date: {'type': 'int', 'logicalType': 'date'},
    _dt.time: {'type': 'long', 'logicalType': 'time-micros'},
}

_FALLBACK_AVRO_TYPE = 'string'
"""Used for annotations we cannot map. Lenient by design — an unmappable field
should not stop the other fields from being published."""


def _record_schema(
    struct_cls: type[msgspec.Struct], *, defined: dict[type, str]
) -> dict:
    """Build an Avro record schema for ``struct_cls``."""
    defined[struct_cls] = struct_cls.__name__

    fields: list[dict[str, Any]] = []
    for field in msgspec.structs.fields(struct_cls):
        avro_type = _avro_type_for(field.type, defined=defined)
        entry: dict[str, Any] = {'name': field.name, 'type': avro_type}

        default = _avro_default_for(field, avro_type)
        if default is not _NO_AVRO_DEFAULT:
            entry['default'] = default

        fields.append(entry)

    return {'type': 'record', 'name': struct_cls.__name__, 'fields': fields}


def _avro_type_for(annotation: Any, *, defined: dict[type, str]) -> Any:
    """Map a single msgspec field annotation to an Avro type."""
    # Optional[X] / X | None / Union[...] — a union in Python is a union in Avro.
    members = _union_members(annotation)
    if members is not None:
        branches: list[Any] = []
        # 'null' must come first so a `"default": null` is legal: Avro validates
        # a union default against the *first* branch only.
        if type(None) in members:
            branches.append('null')
        for member in members:
            if member is type(None):
                continue
            mapped = _avro_type_for(member, defined=defined)
            if mapped not in branches:
                branches.append(mapped)
        if not branches:
            return _FALLBACK_AVRO_TYPE
        return branches[0] if len(branches) == 1 else branches

    if annotation in _LOGICAL_AVRO_TYPES:
        return _LOGICAL_AVRO_TYPES[annotation]

    if annotation in _SCALAR_AVRO_TYPES:
        return _SCALAR_AVRO_TYPES[annotation]

    origin = typing.get_origin(annotation)

    if origin in (list, set, frozenset, tuple):
        args = typing.get_args(annotation)
        item = _avro_type_for(args[0], defined=defined) if args else _FALLBACK_AVRO_TYPE
        return {'type': 'array', 'items': item}

    if origin is dict:
        args = typing.get_args(annotation)
        # Avro map keys are always strings; only the value type is expressible.
        value = (
            _avro_type_for(args[1], defined=defined)
            if len(args) == 2
            else _FALLBACK_AVRO_TYPE
        )
        return {'type': 'map', 'values': value}

    # Bare list/dict annotations carry no parameter to inspect.
    if annotation is list:
        return {'type': 'array', 'items': _FALLBACK_AVRO_TYPE}
    if annotation is dict:
        return {'type': 'map', 'values': _FALLBACK_AVRO_TYPE}

    if isinstance(annotation, type) and issubclass(annotation, msgspec.Struct):
        # A named type may only be *defined* once per schema; later references
        # must use the bare name or fastavro rejects it as a redefinition.
        if annotation in defined:
            return defined[annotation]
        return _record_schema(annotation, defined=defined)

    if isinstance(annotation, type) and issubclass(annotation, _enum_bases()):
        return {
            'type': 'enum',
            'name': annotation.__name__,
            'symbols': [member.name for member in annotation],  # type: ignore[union-attr]
        }

    return _FALLBACK_AVRO_TYPE


def _union_members(annotation: Any) -> tuple[Any, ...] | None:
    """Return union members, or ``None`` when ``annotation`` is not a union.

    Covers both spellings: ``Optional[str]`` / ``Union[...]`` and the PEP 604
    ``str | None`` form msgspec reports for modern annotations.
    """
    origin = typing.get_origin(annotation)
    if origin is Union or isinstance(annotation, _types.UnionType):
        return typing.get_args(annotation)
    return None


class _NoAvroDefault:
    """Sentinel: this field should not emit an Avro ``default``."""


_NO_AVRO_DEFAULT = _NoAvroDefault()


def _avro_default_for(field: Any, avro_type: Any) -> Any:
    """Return the Avro ``default`` for ``field``, or the no-default sentinel.

    Only statically-known, JSON-representable defaults are emitted. A
    ``default_factory`` (``event_id``, ``timestamp``) is deliberately skipped —
    its value is computed per instance and cannot be expressed in a schema.
    """
    # A nullable field always gets `null`, which is what makes it optional for
    # readers — this is the fix for `TypeError: must be string on field source`.
    if isinstance(avro_type, list) and avro_type and avro_type[0] == 'null':
        return None

    default = getattr(field, 'default', msgspec.NODEFAULT)
    if default is msgspec.NODEFAULT:
        return _NO_AVRO_DEFAULT
    if isinstance(default, (str, int, float, bool)) or default is None:
        return default
    return _NO_AVRO_DEFAULT


def _enum_bases() -> tuple[type, ...]:
    import enum

    return (enum.Enum,)
