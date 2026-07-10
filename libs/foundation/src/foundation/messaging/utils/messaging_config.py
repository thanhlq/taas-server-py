from dataclasses import dataclass, field
from typing import Literal, Optional

from core.messaging.types import MessageEncodingType
from core.conf import AppSetting, get_app_settings
from core.messaging.sr import SchemaRegistryConfig


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagingConfig:
    """
    Provider-agnostic messaging configuration.

    Aggregates every knob currently read from :class:`AppSetting` by
    :class:`BaseMessagingService` and its Kafka subclasses
    (``AiokafkaMessagingService``, ``FastStreamKafkaMessagingService``).

    Built once via :func:`build_messaging_config` and stored on the service as
    ``self.messaging_config`` so handlers don't need to reach back into
    :class:`AppSetting` for individual values.
    """

    # ---- Encoding -----------------------------------------------------------
    message_encoding: str = 'msgpack'
    """Wire encoding: ``json`` | ``msgpack`` | ``protobuf`` | ``schema-registry-avro``."""

    message_field_encoding: str = 'msgpack'
    """Per-field encoding used when ``message_encoding='schema-registry-avro'``."""

    # ---- Provider selection -------------------------------------------------
    pubsub_provider: str = 'kafka'
    """Active pub/sub backend: ``kafka`` | ``faststream-kafka`` | ``redis`` | ``sqs``."""

    # ---- Concurrency / lifecycle -------------------------------------------
    max_concurrent_tasks: int = 10
    """Upper bound on in-flight message handlers per consumer."""

    graceful_shutdown_timeout: int = 5
    """Seconds to wait for in-flight tasks and broker close on stop()."""

    # ---- Retry / DLQ --------------------------------------------------------
    max_retries: int = 3
    """Default per-message retry budget before DLQ routing."""

    retry_backoff_ms: int = 1000
    """Initial backoff between retries (linear/expo policy lives in the retry layer)."""

    dlq_enabled: bool = True
    """Forward terminally-failed messages to ``dlq_topic`` for offline analysis."""

    dlq_topic: str = 'dlq.events'
    """Topic that receives DLQ envelopes (:class:`DlqEvent`)."""

    # ---- Kafka: connection --------------------------------------------------
    kafka_bootstrap_servers: str = 'localhost:9092'
    """Comma-separated broker addresses (``host1:9092,host2:9092``)."""

    kafka_topics: list[str] = field(default_factory=list)
    """Topics statically subscribed in worker (consumer) mode."""

    kafka_consumer_enable: bool = False
    """True in worker processes, False in API-only processes."""

    consumer_group_id: str = 'eworksuite-worker-group'
    """
    Kafka consumer group ID — shared by all instances of a worker.
    Same group id means multiple instances will share the topic partitions and load-balance
    messages between them. Different group ids means each instance gets a full copy of the topic traffic.
    """

    kafka_auto_offset_reset: Literal['latest', 'earliest', 'none'] = 'earliest'
    """Offset-reset policy when no committed offset exists."""

    kafka_enable_auto_commit: bool = False
    """``False`` keeps offset commits in the EventProcessor (recommended)."""

    kafka_max_poll_records: int = 500
    """Maximum records returned per ``consumer.poll()`` call."""

    kafka_session_timeout_ms: int = 30_000
    """Group-membership session timeout sent to the broker."""

    kafka_heartbeat_interval_ms: int = 3_000
    """Background heartbeat cadence; must be < ``kafka_session_timeout_ms / 3``."""

    # ---- Kafka: security ----------------------------------------------------
    kafka_security_protocol: Optional[str] = None
    """``PLAINTEXT`` | ``SSL`` | ``SASL_PLAINTEXT`` | ``SASL_SSL`` (None = PLAINTEXT)."""

    kafka_sasl_mechanism: Optional[str] = None
    """``PLAIN`` | ``SCRAM-SHA-256`` | ``SCRAM-SHA-512`` when SASL is used."""

    kafka_sasl_username: Optional[str] = None
    kafka_sasl_password: Optional[str] = None

    # ---- Schema Registry ----------------------------------------------------
    schema_registry_url: Optional[str] = None
    """Confluent Schema Registry endpoint (required for ``schema-registry-avro``)."""

    schema_registry_username: Optional[str] = None
    schema_registry_password: Optional[str] = None

    # ---- Outbox -------------------------------------------------------------
    outbox_enabled: bool = False
    """When True, ``publish()`` writes to the outbox table instead of sending directly."""

    outbox_poller_enabled: bool = False
    """Enable the background outbox poller in this process (worker only)."""

    # ------------------------------------------------------------------ helpers

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        """Split ``kafka_bootstrap_servers`` into a list."""
        return [s.strip() for s in self.kafka_bootstrap_servers.split(',') if s.strip()]

    @property
    def schema_registry_enabled(self) -> bool:
        return self.message_encoding == MessageEncodingType.SCHEMA_REGISTRY_AVRO

    def build_schema_registry_config(self) -> Optional[SchemaRegistryConfig]:
        """Materialise a :class:`SchemaRegistryConfig` if SR encoding is active."""
        if not self.schema_registry_enabled or not self.schema_registry_url:
            return None
        return SchemaRegistryConfig(
            url=self.schema_registry_url,
            username=self.schema_registry_username,
            password=self.schema_registry_password,
        )

    def __post_init__(self) -> None:
        if self.kafka_auto_offset_reset not in {'latest', 'earliest', 'none'}:
            raise ValueError(
                f'Invalid kafka_auto_offset_reset={self.kafka_auto_offset_reset!r}; '
                "must be one of 'latest', 'earliest', 'none'"
            )
        if self.max_concurrent_tasks < 1:
            raise ValueError('max_concurrent_tasks must be >= 1')
        if self.graceful_shutdown_timeout < 0:
            raise ValueError('graceful_shutdown_timeout must be >= 0')


def build_messaging_config(
    settings: Optional[AppSetting] = None,
) -> MessagingConfig:
    """
    Materialise :class:`BaseMessagingConfig` from :class:`AppSetting`.

    Centralises the env→config mapping so subclasses don't reach into
    ``AppSetting`` directly. Pass an explicit ``settings`` instance for
    testing; otherwise the cached app settings singleton is used.
    """
    s = settings or get_app_settings()
    return MessagingConfig(
        # encoding
        message_encoding=s.MESSAGE_ENCODING,
        message_field_encoding=s.MESSAGE_FIELD_ENCODING,
        # provider
        pubsub_provider=s.PUBSUB_SERVICE_PROVIDER,
        # concurrency
        max_concurrent_tasks=s.MAX_CONCURRENT_TASKS,
        graceful_shutdown_timeout=s.GRACEFUL_SHUTDOWN_TIMEOUT,
        # retry / DLQ
        max_retries=s.MAX_RETRIES,
        retry_backoff_ms=s.RETRY_BACKOFF_MS,
        dlq_enabled=s.DLQ_ENABLE,
        dlq_topic=s.DLQ_TOPIC,
        # kafka connection
        kafka_bootstrap_servers=s.KAFKA_BOOTSTRAP_SERVERS,
        kafka_topics=list(s.KAFKA_TOPICS),
        kafka_consumer_enable=s.KAFKA_CONSUMER_ENABLE,
        consumer_group_id=s.KAFKA_CONSUMER_GROUP_ID,
        kafka_auto_offset_reset=s.KAFKA_AUTO_OFFSET_RESET,
        kafka_enable_auto_commit=s.KAFKA_ENABLE_AUTO_COMMIT,
        kafka_max_poll_records=s.KAFKA_MAX_POLL_RECORDS,
        kafka_session_timeout_ms=s.KAFKA_SESSION_TIMEOUT_MS,
        kafka_heartbeat_interval_ms=s.KAFKA_HEARTBEAT_INTERVAL_MS,
        # kafka security
        kafka_security_protocol=s.KAFKA_SECURITY_PROTOCOL,
        kafka_sasl_mechanism=s.KAFKA_SASL_MECHANISM,
        kafka_sasl_username=s.KAFKA_SASL_USERNAME,
        kafka_sasl_password=s.KAFKA_SASL_PASSWORD,
        # schema registry
        schema_registry_url=s.KAFKA_SCHEMA_REGISTRY_URL,
        schema_registry_username=s.KAFKA_SCHEMA_REGISTRY_USERNAME,
        schema_registry_password=s.KAFKA_SCHEMA_REGISTRY_PASSWORD,
        # outbox
        outbox_enabled=s.OUTBOX_ENABLE,
        outbox_poller_enabled=s.OUTBOX_POLLER_ENABLE,
    )
