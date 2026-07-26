from typing import Any

import msgspec
from foundation.serialization import BaseEvent
from foundation.utils.predicates import is_dataclass_class


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
    # Implement the conversion logic from msgspec.Struct to Avro schema here.
    # This is a placeholder implementation and should be replaced with actual logic.
    avro_schema = {
        'type': 'record',
        'name': schema_cls.__name__,
        'fields': [
            {
                'name': field.name,
                'type': _map_msgspec_type_to_avro.get(field.type, 'string'),
            }
            for field in msgspec.structs.fields(schema_cls)
        ],
    }
    return avro_schema


_map_msgspec_type_to_avro = {
    int: 'int',
    float: 'float',
    str: 'string',
    bool: 'boolean',
    list: {'type': 'array', 'items': 'string'},  # Placeholder for list type mapping
    dict: {'type': 'map', 'values': 'string'},  # Add more type mappings as needed
}
