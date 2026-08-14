"""
🔧 FastStream Kafka Helper Utilities

Provides trace-context extraction and header conversion utilities for
FastStream's ``KafkaMessage`` objects.

These are thin wrappers around the raw aiokafka ``ConsumerRecord`` headers
so that the rest of the service code never needs to touch the underlying
protocol details directly.
"""

from __future__ import annotations

from typing import Optional

from faststream.kafka import KafkaMessage


class FastStreamHelper:
    """
    Static utility methods for working with FastStream Kafka messages.

    All methods are static / class-methods — instantiation is not needed.
    """

    @staticmethod
    def find_traceparent(message: KafkaMessage) -> Optional[str]:
        """Extract the W3C ``traceparent`` header from a Kafka message.

        FastStream normalises Kafka headers into a ``dict[str, Any]`` on
        ``message.headers``.  The raw aiokafka header values may be
        ``bytes`` (wire representation) or ``str`` (already decoded by
        FastStream).  This method handles both transparently.

        Args:
            message: Incoming FastStream ``KafkaMessage``.

        Returns:
            The ``traceparent`` string if present, otherwise ``None``.

        Example::

            traceparent = FastStreamHelper.find_traceparent(msg)
            # "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        """
        if not message or not message.headers:
            return None

        for key, value in message.headers.items():
            if key.lower() == 'traceparent':
                if isinstance(value, bytes):
                    return value.decode('utf-8', errors='replace')
                traceparent = str(value)
                print(f'👓 Extracted traceparent from Kafka message header: {traceparent}')
                return traceparent

        return None

    @staticmethod
    def extract_headers(message: KafkaMessage) -> dict[str, str]:
        """Return all Kafka headers as a plain ``dict[str, str]``.

        Byte values are UTF-8 decoded.  Non-string keys are coerced with
        ``str()``.  This is safe to pass directly to ``broker.publish()``
        as the ``headers`` keyword argument.

        Args:
            message: Incoming FastStream ``KafkaMessage``.

        Returns:
            Decoded header dict, possibly empty.
        """
        if not message or not message.headers:
            return {}

        result: dict[str, str] = {}
        for key, value in message.headers.items():
            str_key = key if isinstance(key, str) else str(key) # type: ignore
            if isinstance(value, bytes):
                result[str_key] = value.decode('utf-8', errors='replace')
            else:
                result[str_key] = str(value)
        return result

    @staticmethod
    def build_publish_headers(
        traceparent: Optional[str] = None,
        extra: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """Build a headers dict suitable for ``broker.publish(..., headers=...)``.

        Merges an optional ``traceparent`` with any additional *extra* headers.
        ``None`` values are omitted so Kafka doesn't receive empty header bytes.

        Args:
            traceparent: W3C Trace Context traceparent string, or ``None``.
            extra: Any additional ``str → str`` headers.

        Returns:
            Combined header dict.
        """
        headers: dict[str, str] = {}
        if traceparent:
            headers['traceparent'] = traceparent
        if extra:
            headers.update({k: v for k, v in extra.items() if v is not None}) # type: ignore
        return headers
