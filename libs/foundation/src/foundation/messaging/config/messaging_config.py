import ssl
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from foundation.messaging.types import MessageEncodingType
from foundation.utils.ca_data_utils import normalize_ca_data

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from ..kafka.sr import SchemaRegistryConfig




KAFKA_SECURITY_PROTOCOLS = frozenset({'PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'})
"""The four protocol names Kafka accepts in ``listener.security.protocol.map``."""

KAFKA_SASL_MECHANISMS = frozenset(
    {'PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512', 'GSSAPI', 'OAUTHBEARER'}
)
"""SASL mechanisms an aiokafka client can negotiate."""

KAFKA_SASL_PASSWORD_MECHANISMS = frozenset({'PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512'})
"""Subset of :data:`KAFKA_SASL_MECHANISMS` that authenticates with user/password."""



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

    consumer_channels: list[str] = field(default_factory=list)
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

    

    kafka_security_protocol: Optional[str] = None
    """
    Transport framing + whether a SASL handshake happens at all.

    One of :data:`KAFKA_SECURITY_PROTOCOLS`; ``None`` is treated as ``PLAINTEXT``.
    Must match the broker listener you are connecting to — a mismatch fails at
    the first handshake, not at startup. Normalized to upper case.
    """

    kafka_sasl_mechanism: Optional[str] = None
    """
    Which SASL mechanism proves identity, once the protocol says SASL runs.

    One of :data:`KAFKA_SASL_MECHANISMS`; required when (and only when)
    ``kafka_security_protocol`` starts with ``SASL_``. Normalized to upper case
    with ``_`` folded to ``-`` (so ``scram_sha_512`` → ``SCRAM-SHA-512``).
    Says nothing about encryption — that is the protocol's job.
    """

    kafka_sasl_username: Optional[str] = None
    """SASL identity. Required for :data:`KAFKA_SASL_PASSWORD_MECHANISMS`."""

    kafka_sasl_password: Optional[str] = None
    """SASL secret. Required for :data:`KAFKA_SASL_PASSWORD_MECHANISMS`."""

    kafka_ssl_ca_location: Optional[str] = None
    """
    Path to the PEM CA bundle that signs the broker certificate.

    Highest-precedence trust anchor; use when the CA is mounted as a file.
    Ignored unless the protocol is TLS-bearing (``SSL``/``SASL_SSL``).
    """

    kafka_ssl_ca_data: Optional[str] = None
    """
    The same CA bundle carried inline, for when it arrives as a variable
    instead of a file (K8s secret, CI/CD store). Accepts multi-line PEM,
    single-line PEM with ``\\n`` escapes, or base64 PEM.
    Used only when ``kafka_ssl_ca_location`` is unset.
    """

    kafka_ssl_check_hostname: bool = True
    """
    Verify the broker's certificate matches the hostname you dialed.

    Turning this off still verifies the chain, but accepts *any* host the CA
    signed — acceptable for a dev cluster reached by IP, never in production.
    """

    kafka_ssl_strict_verify: bool = True
    """
    Apply the RFC 5280 strict checks Python 3.13+ enables by default.

    Set ``False`` for private CAs that omit the ``keyUsage`` extension (e.g. a
    hand-rolled Strimzi cluster CA). Chain and hostname verification stay on.
    """

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
    def kafka_effective_security_protocol(self) -> str:
        """The protocol actually used on the wire (``None`` means ``PLAINTEXT``)."""
        return self.kafka_security_protocol or 'PLAINTEXT'

    @property
    def kafka_tls_enabled(self) -> bool:
        """True for ``SSL``/``SASL_SSL`` — the connection is TLS-wrapped."""
        return self.kafka_effective_security_protocol.endswith('SSL')

    @property
    def kafka_sasl_enabled(self) -> bool:
        """True for ``SASL_PLAINTEXT``/``SASL_SSL`` — a SASL handshake runs."""
        return self.kafka_effective_security_protocol.startswith('SASL')

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
        if not self.kafka_tls_enabled:
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

    def _normalize_kafka_security(self) -> None:
        """
        Canonicalise the security pair so every provider sees identical values.

        Env vars arrive lower-cased, whitespace-padded, or empty (``VAR=`` yields
        ``''``, not ``None``). Folding that here — once, at construction — is
        what keeps the providers in agreement: they used to case-fold
        differently, so a lower-case ``sasl_ssl`` disabled TLS on the aiokafka
        path while the FastStream path still enabled it.
        """
        protocol = (self.kafka_security_protocol or '').strip().upper()
        mechanism = (self.kafka_sasl_mechanism or '').strip().upper().replace('_', '-')
        object.__setattr__(self, 'kafka_security_protocol', protocol or None)
        object.__setattr__(self, 'kafka_sasl_mechanism', mechanism or None)

    def _validate_kafka_security(self) -> None:
        """
        Reject security combinations that would otherwise fail silently or late.

        Protocol and mechanism are orthogonal but overlap on one bit — whether
        SASL runs — so a config can state that bit twice and contradict itself.
        Each case below used to be swallowed: the credential was quietly
        dropped, or a mechanism was quietly guessed.
        """
        protocol = self.kafka_security_protocol
        mechanism = self.kafka_sasl_mechanism

        if protocol is not None and protocol not in KAFKA_SECURITY_PROTOCOLS:
            raise ValueError(
                f'Invalid KAFKA_SECURITY_PROTOCOL={protocol!r}; must be one of '
                f'{sorted(KAFKA_SECURITY_PROTOCOLS)}'
            )
        if mechanism is not None and mechanism not in KAFKA_SASL_MECHANISMS:
            raise ValueError(
                f'Invalid KAFKA_SASL_MECHANISM={mechanism!r}; must be one of '
                f'{sorted(KAFKA_SASL_MECHANISMS)}'
            )

        if not self.kafka_sasl_enabled:
            if mechanism is not None:
                raise ValueError(
                    f'KAFKA_SASL_MECHANISM={mechanism!r} is set but '
                    f'KAFKA_SECURITY_PROTOCOL={self.kafka_effective_security_protocol!r} '
                    'runs no SASL handshake, so the credential would be ignored. '
                    'Use SASL_SSL (with TLS) or SASL_PLAINTEXT (without), '
                    'or unset the mechanism.'
                )
            return

        if mechanism is None:
            raise ValueError(
                f'KAFKA_SECURITY_PROTOCOL={protocol!r} performs a SASL handshake, '
                'so KAFKA_SASL_MECHANISM must be set explicitly (one of '
                f'{sorted(KAFKA_SASL_MECHANISMS)}); refusing to guess PLAIN.'
            )
        if mechanism in KAFKA_SASL_PASSWORD_MECHANISMS:
            missing = [
                name
                for name, value in (
                    ('KAFKA_SASL_USERNAME', self.kafka_sasl_username),
                    ('KAFKA_SASL_PASSWORD', self.kafka_sasl_password),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f'KAFKA_SASL_MECHANISM={mechanism!r} authenticates with a '
                    f'username/password pair; missing: {", ".join(missing)}'
                )

    def __post_init__(self) -> None:
        self._normalize_kafka_security()
        self._validate_kafka_security()
        if self.kafka_auto_offset_reset not in {'latest', 'earliest', 'none'}:
            raise ValueError(
                f'Invalid kafka_auto_offset_reset={self.kafka_auto_offset_reset!r}; '
                "must be one of 'latest', 'earliest', 'none'"
            )
        if self.max_concurrent_tasks < 1:
            raise ValueError('max_concurrent_tasks must be >= 1')
        if self.graceful_shutdown_timeout < 0:
            raise ValueError('graceful_shutdown_timeout must be >= 0')
