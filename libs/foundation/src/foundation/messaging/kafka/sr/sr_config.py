from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from foundation.messaging.kafka.kafka_settings import KafkaSettings


@dataclass
class SchemaRegistryConfig:
    """
    Confluent Schema Registry connection configuration.

    Args:
        url: Schema Registry base URL (e.g. ``http://localhost:8081``).
        username: Optional HTTP Basic auth username (Confluent Cloud).
        password: Optional HTTP Basic auth password (Confluent Cloud).
        ssl_verify: Whether to verify the TLS certificate (default ``True``).
        timeout_seconds: HTTP request timeout in seconds (default ``30``).

    Example::

        # Local dev
        config = SchemaRegistryConfig(url="http://localhost:8081")

        # Confluent Cloud
        config = SchemaRegistryConfig(
            url="https://my-registry.confluent.cloud",
            username="API_KEY",
            password="API_SECRET",
        )
    """

    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    ssl_verify: bool = True
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        self.url = self.url.rstrip('/')

    @property
    def auth(self) -> Optional[tuple[str, str]]:
        """Return ``(username, password)`` tuple or ``None`` if not configured."""
        if self.username and self.password:
            return (self.username, self.password)
        return None


def build_schema_registry_config(config: KafkaSettings) -> SchemaRegistryConfig:
    """Materialise a :class:`SchemaRegistryConfig` if SR encoding is active."""
    if config.KAFKA_SCHEMA_REGISTRY_URL is None:
        raise ValueError(
            'MESSAGE_ENCODING is schema-registry-avro but '
            'KAFKA_SCHEMA_REGISTRY_URL is not configured.'
        )

    return SchemaRegistryConfig(
        url=config.KAFKA_SCHEMA_REGISTRY_URL,
        username=config.KAFKA_SCHEMA_REGISTRY_USERNAME,
        password=config.KAFKA_SCHEMA_REGISTRY_PASSWORD,
    )
