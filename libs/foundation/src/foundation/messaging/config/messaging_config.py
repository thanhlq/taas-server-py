import base64
import binascii
import ssl
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from foundation.messaging.types import MessageEncodingType

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from ..kafka.sr import SchemaRegistryConfig


PEM_CERT_MARKER = '-----BEGIN CERTIFICATE-----'


def normalize_ca_data(raw: str) -> str:
    """
    Turn an env-var-carried CA bundle into PEM text OpenSSL accepts.

    Handles the three shapes a CA realistically arrives in when it is injected
    as a variable rather than mounted as a file:

    * plain multi-line PEM (dotenv quoted value, Docker/K8s multi-line env),
    * single-line PEM with literal ``\\n`` escapes (CI/CD secret stores),
    * base64-encoded PEM (e.g. a Kubernetes secret's raw ``ca.crt`` value).

    Raises ``ValueError`` when the result still isn't a certificate, so a
    mangled secret fails at startup instead of at the first TLS handshake.
    """
    data = raw.strip()

    if PEM_CERT_MARKER not in data:
        # Not PEM as-is — the only other sane encoding is base64-wrapped PEM.
        try:
            data = base64.b64decode(data, validate=True).decode('ascii').strip()
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(
                'KAFKA_CA_DATA is neither PEM nor base64-encoded PEM'
            ) from exc

    # Secret stores commonly flatten newlines into the two-character escape.
    data = data.replace('\\n', '\n').strip()

    if PEM_CERT_MARKER not in data:
        raise ValueError(
            f'KAFKA_CA_DATA does not contain a {PEM_CERT_MARKER!r} block'
        )

    # OpenSSL requires the PEM to end with a newline.
    return data + '\n'


@lru_cache(maxsize=8)
def _build_ssl_context(
    ca_location: Optional[str],
    ca_data: Optional[str],
    check_hostname: bool,
    strict_verify: bool,
) -> ssl.SSLContext:
    """
    Build a client TLS context, cached per distinct set of TLS settings.

    Kafka clients take the trust anchor as an :class:`ssl.SSLContext` rather
    than a ``ssl.ca.location``-style path, so the PEM bundle is loaded here.
    Trust anchor precedence: CA file → inline CA data → system trust store.
    """
    if ca_location:
        ca_path = Path(ca_location).expanduser()
        if not ca_path.is_file():
            raise FileNotFoundError(
                f'KAFKA_SSL_CA_LOCATION points to a missing file: {ca_path}'
            )
        context = ssl.create_default_context(cafile=str(ca_path))
    elif ca_data:
        context = ssl.create_default_context(cadata=normalize_ca_data(ca_data))
    else:
        context = ssl.create_default_context()

    if not strict_verify:
        # Python 3.13+ enables VERIFY_X509_STRICT by default, which rejects CA
        # certificates lacking a keyUsage extension — common for private CAs
        # (e.g. a hand-rolled Strimzi cluster CA). Chain and hostname
        # verification stay on; only the RFC 5280 strictness checks are relaxed.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT

    if not check_hostname:
        context.check_hostname = False
    return context


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

    consumer_topics: list[str] = field(default_factory=list)
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
    """
    ``PLAINTEXT`` | ``SSL`` | ``SASL_PLAINTEXT`` | ``SASL_SSL`` (None = PLAINTEXT).

    - PLAINTEXT: no TLS, no SASL
    - SSL: TLS only, no SASL
    - SASL_PLAINTEXT: SASL auth, no TLS
    - SASL_SSL: SASL auth over TLS

    """

    kafka_sasl_mechanism: Optional[str] = None
    """``PLAIN`` | ``SCRAM-SHA-256`` | ``SCRAM-SHA-512`` when SASL is used."""

    kafka_sasl_username: Optional[str] = None
    kafka_sasl_password: Optional[str] = None

    kafka_ssl_ca_location: Optional[str] = None
    """Path to a PEM CA bundle used to verify the broker certificate (SSL/SASL_SSL)."""

    kafka_ssl_ca_data: Optional[str] = None
    """Inline CA bundle (PEM, escaped PEM, or base64 PEM) — used when no CA file is set."""

    kafka_ssl_check_hostname: bool = True
    """Verify the broker hostname against its certificate; disable only for dev."""

    kafka_ssl_strict_verify: bool = True
    """Apply RFC 5280 strict checks (Python 3.13+ default); off for CAs without keyUsage."""

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
    def kafka_ssl_trust_source(self) -> str:
        """Human-readable description of where the TLS trust anchor comes from."""
        if self.kafka_ssl_ca_location:
            return f'file:{self.kafka_ssl_ca_location}'
        if self.kafka_ssl_ca_data:
            return f'inline KAFKA_CA_DATA ({len(self.kafka_ssl_ca_data)} chars)'
        return 'system trust store'

    def build_kafka_client_kwargs(self) -> dict[str, Any]:
        """
        Security kwargs accepted by every aiokafka client class.

        Shared by the producer/consumer/admin clients so a single config change
        applies everywhere. Omitted keys leave the aiokafka defaults in place.
        """
        kw: dict[str, Any] = {}
        if self.kafka_security_protocol:
            kw['security_protocol'] = self.kafka_security_protocol
        if self.kafka_sasl_mechanism:
            kw['sasl_mechanism'] = self.kafka_sasl_mechanism
        if self.kafka_sasl_username:
            kw['sasl_plain_username'] = self.kafka_sasl_username
        if self.kafka_sasl_password:
            kw['sasl_plain_password'] = self.kafka_sasl_password
        ssl_context = self.build_kafka_ssl_context()
        if ssl_context is not None:
            kw['ssl_context'] = ssl_context
        return kw

    def build_kafka_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        TLS context for ``SSL``/``SASL_SSL`` brokers, ``None`` otherwise.

        ``None`` means "no ssl_context kwarg" — correct for PLAINTEXT and
        SASL_PLAINTEXT connections.
        """
        if not (self.kafka_security_protocol or '').endswith('SSL'):
            return None
        return _build_ssl_context(
            self.kafka_ssl_ca_location,
            self.kafka_ssl_ca_data,
            self.kafka_ssl_check_hostname,
            self.kafka_ssl_strict_verify,
        )

    @property
    def schema_registry_enabled(self) -> bool:
        return self.message_encoding == MessageEncodingType.SCHEMA_REGISTRY_AVRO

    def build_schema_registry_config(self) -> Optional['SchemaRegistryConfig']:
        """Materialise a :class:`SchemaRegistryConfig` if SR encoding is active."""
        if not self.schema_registry_enabled or not self.schema_registry_url:
            return None
        from ..kafka.sr import SchemaRegistryConfig

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
