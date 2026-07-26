import struct
from .types import WireFormatError

# ---------------------------------------------------------------------------
# Wire Format
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Wire Format Constants
# ---------------------------------------------------------------------------

MAGIC_BYTE: int = 0x00
"""Confluent Schema Registry magic byte that identifies the wire format."""

WIRE_FORMAT_HEADER_SIZE: int = 5
"""Total bytes for magic byte (1) + schema ID (4)."""

class ConfluentWireFormat:
    """
    Encode / decode the Confluent Schema Registry wire format.

    This is a static utility class — instantiation is not required.

    Wire format::

        byte 0   : magic byte (0x00)
        bytes 1-4: schema ID as big-endian unsigned 32-bit integer
        bytes 5+ : Avro or JSON Schema serialised payload
    """

    @staticmethod
    def encode(schema_id: int, payload: bytes) -> bytes:
        """Prepend the Confluent wire-format header to *payload*.

        Args:
            schema_id: The schema ID returned by the Schema Registry.
            payload: The already-serialised Avro/JSON bytes.

        Returns:
            Header (5 bytes) + payload.
        """
        header = struct.pack('>bI', MAGIC_BYTE, schema_id)
        return header + payload

    @staticmethod
    def decode(data: bytes) -> tuple[int, bytes]:
        """Strip and parse the Confluent wire-format header from *data*.

        Args:
            data: Raw bytes received from Kafka.

        Returns:
            ``(schema_id, payload)`` where *payload* is everything after the header.

        Raises:
            ValueError: If the data is too short or the magic byte is wrong.
        """
        if len(data) < WIRE_FORMAT_HEADER_SIZE:
            raise WireFormatError(
                f'Message too short for Confluent wire format: '
                f'expected >= {WIRE_FORMAT_HEADER_SIZE} bytes, got {len(data)}'
            )
        magic, schema_id = struct.unpack('>bI', data[:WIRE_FORMAT_HEADER_SIZE])
        if magic != MAGIC_BYTE:
            raise WireFormatError(
                f'Invalid magic byte: {magic:#x} (expected {MAGIC_BYTE:#x}). '
                'Is the message using Confluent wire format?'
            )
        return schema_id, data[WIRE_FORMAT_HEADER_SIZE:]

