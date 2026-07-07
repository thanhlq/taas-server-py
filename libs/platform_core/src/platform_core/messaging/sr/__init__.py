from .sr_config import SchemaRegistryConfig
from .types import (
    ISchemaRegistryClient,
    ISchemaRegistryEncoder,
    ISchemaSerializer,
    IWireFormat,
    SchemaNotFoundError,
    SchemaRegistryError,
    WireFormatError,
)
from .confluent import ConfluentWireFormat

#
# Export one of fastavro or legacy implementations
#

# Default implementation using fastavro + httpx, kept here as the default.
from .schema_registry_fast import (
    SchemaRegistryEncoder,
    SchemaRegistryClient,
)

# Uncomment the following lines to export the legacy implementation instead of the default.
# from .schema_registry_legacy import (
#     LegacySchemaRegistryEncoder as SchemaRegistryEncoder,
#     LegacySchemaRegistryClient as SchemaRegistryClient,
# )


__all__ = [
    # Config
    'SchemaRegistryConfig',
    # Interfaces (for typing / new implementations)
    'ISchemaRegistryClient',
    'ISchemaRegistryEncoder',
    'ISchemaSerializer',
    'IWireFormat',
    # Errors (shared across implementations)
    'SchemaRegistryError',
    'SchemaNotFoundError',
    # Default Confluent (fastavro + httpx) implementation
    'SchemaRegistryClient',
    'SchemaRegistryEncoder',
    'WireFormatError',
    'ConfluentWireFormat',
]
