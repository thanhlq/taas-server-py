from dataclasses import dataclass, field
from typing import Literal, cast

from foundation.utils.env_utils import get_env

from ..config.messaging_config import MessagingConfig


@dataclass
class KafkaSettings:
    """Kafka settings."""

    # encoding
    MESSAGE_ENCODING: str = field(
        default_factory=get_env('MESSAGE_ENCODING', 'msgpack')
    )
    MESSAGE_FIELD_ENCODING: str = field(
        default_factory=get_env('MESSAGE_FIELD_ENCODING', 'msgpack')
    )

    # provider
    PUBSUB_SERVICE_PROVIDER: str = field(
        default_factory=get_env('PUBSUB_SERVICE_PROVIDER', 'kafka')
    )

    # concurrency
    MAX_CONCURRENT_TASKS: int = field(
        default_factory=get_env('MAX_CONCURRENT_TASKS', 10)
    )
    GRACEFUL_SHUTDOWN_TIMEOUT: int = field(
        default_factory=get_env('GRACEFUL_SHUTDOWN_TIMEOUT', 5)
    )

    # retry / DLQ
    MAX_RETRIES: int = field(default_factory=get_env('MAX_RETRIES', 3))
    RETRY_BACKOFF_MS: int = field(default_factory=get_env('RETRY_BACKOFF_MS', 1000))
    DLQ_ENABLE: bool = field(default_factory=get_env('DLQ_ENABLE', True, bool))
    DLQ_TOPIC: str = field(default_factory=get_env('DLQ_TOPIC', 'dlq.events'))

    # kafka connection
    KAFKA_BOOTSTRAP_SERVERS: str = field(
        default_factory=get_env('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    )
    KAFKA_TOPICS: list[str] = field(
        default_factory=get_env('KAFKA_TOPICS', [], list[str])
    )
    KAFKA_CONSUMER_ENABLE: bool = field(
        default_factory=get_env('KAFKA_CONSUMER_ENABLE', True, bool)
    )
    KAFKA_CONSUMER_GROUP_ID: str = field(
        default_factory=get_env('KAFKA_CONSUMER_GROUP_ID', 'eworksuite-worker-group')
    )
    KAFKA_AUTO_OFFSET_RESET: str = field(
        default_factory=get_env('KAFKA_AUTO_OFFSET_RESET', 'earliest')
    )
    KAFKA_ENABLE_AUTO_COMMIT: bool = field(
        default_factory=get_env('KAFKA_ENABLE_AUTO_COMMIT', False, bool)
    )
    KAFKA_MAX_POLL_RECORDS: int = field(
        default_factory=get_env('KAFKA_MAX_POLL_RECORDS', 500)
    )
    KAFKA_SESSION_TIMEOUT_MS: int = field(
        default_factory=get_env('KAFKA_SESSION_TIMEOUT_MS', 30_000)
    )
    KAFKA_HEARTBEAT_INTERVAL_MS: int = field(
        default_factory=get_env('KAFKA_HEARTBEAT_INTERVAL_MS', 3_000)
    )

    # kafka security
    KAFKA_SECURITY_PROTOCOL: str | None = field(
        default_factory=get_env('KAFKA_SECURITY_PROTOCOL', None, str)
    )
    KAFKA_SASL_MECHANISM: str | None = field(
        default_factory=get_env('KAFKA_SASL_MECHANISM', None, str)
    )
    KAFKA_SASL_USERNAME: str | None = field(
        default_factory=get_env('KAFKA_SASL_USERNAME', None, str)
    )
    KAFKA_SASL_PASSWORD: str | None = field(
        default_factory=get_env('KAFKA_SASL_PASSWORD', None, str)
    )

    # schema registry
    KAFKA_SCHEMA_REGISTRY_URL: str | None = field(
        default_factory=get_env('KAFKA_SCHEMA_REGISTRY_URL', None, str)
    )
    KAFKA_SCHEMA_REGISTRY_USERNAME: str | None = field(
        default_factory=get_env('KAFKA_SCHEMA_REGISTRY_USERNAME', None, str)
    )
    KAFKA_SCHEMA_REGISTRY_PASSWORD: str | None = field(
        default_factory=get_env('KAFKA_SCHEMA_REGISTRY_PASSWORD', None, str)
    )

    # outbox
    OUTBOX_ENABLE: bool = field(default_factory=get_env('OUTBOX_ENABLE', False, bool))
    OUTBOX_POLLER_ENABLE: bool = field(
        default_factory=get_env('OUTBOX_POLLER_ENABLE', False, bool)
    )


def build_messaging_config(
    settings: KafkaSettings,
) -> MessagingConfig:
    """
    Materialise :class:`BaseMessagingConfig` from :class:`AppSetting`.

    Centralises the env→config mapping so subclasses don't reach into
    ``AppSetting`` directly. Pass an explicit ``settings`` instance for
    testing; otherwise the cached app settings singleton is used.
    """
    return MessagingConfig(
        # encoding
        message_encoding=settings.MESSAGE_ENCODING,
        message_field_encoding=settings.MESSAGE_FIELD_ENCODING,
        # provider
        pubsub_provider=settings.PUBSUB_SERVICE_PROVIDER,
        # concurrency
        max_concurrent_tasks=settings.MAX_CONCURRENT_TASKS,
        graceful_shutdown_timeout=settings.GRACEFUL_SHUTDOWN_TIMEOUT,
        # retry / DLQ
        max_retries=settings.MAX_RETRIES,
        retry_backoff_ms=settings.RETRY_BACKOFF_MS,
        dlq_enabled=settings.DLQ_ENABLE,
        dlq_topic=settings.DLQ_TOPIC,
        # kafka connection
        kafka_bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        kafka_topics=list(settings.KAFKA_TOPICS),
        kafka_consumer_enable=settings.KAFKA_CONSUMER_ENABLE,
        consumer_group_id=settings.KAFKA_CONSUMER_GROUP_ID,
        kafka_auto_offset_reset=cast(
            Literal['latest', 'earliest', 'none'],
            settings.KAFKA_AUTO_OFFSET_RESET,
        ),
        kafka_enable_auto_commit=settings.KAFKA_ENABLE_AUTO_COMMIT,
        kafka_max_poll_records=settings.KAFKA_MAX_POLL_RECORDS,
        kafka_session_timeout_ms=settings.KAFKA_SESSION_TIMEOUT_MS,
        kafka_heartbeat_interval_ms=settings.KAFKA_HEARTBEAT_INTERVAL_MS,
        # kafka security
        kafka_security_protocol=settings.KAFKA_SECURITY_PROTOCOL,
        kafka_sasl_mechanism=settings.KAFKA_SASL_MECHANISM,
        kafka_sasl_username=settings.KAFKA_SASL_USERNAME,
        kafka_sasl_password=settings.KAFKA_SASL_PASSWORD,
        # schema registry
        schema_registry_url=settings.KAFKA_SCHEMA_REGISTRY_URL,
        schema_registry_username=settings.KAFKA_SCHEMA_REGISTRY_USERNAME,
        schema_registry_password=settings.KAFKA_SCHEMA_REGISTRY_PASSWORD,
        # outbox
        outbox_enabled=settings.OUTBOX_ENABLE,
        outbox_poller_enabled=settings.OUTBOX_POLLER_ENABLE,
    )
