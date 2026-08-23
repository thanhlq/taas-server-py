from dataclasses import dataclass, field

from foundation.utils.env_utils import get_env


@dataclass
class KafkaSettings:
    """Kafka settings, hashable and comparable for caching and equality checks."""

    # concurrency
    KAFKA_CONSUMER_MAX_WORKERS: int = field(
        default_factory=get_env('KAFKA_CONSUMER_MAX_WORKERS', 1)
    )
    KAFKA_GRACEFUL_SHUTDOWN_TIMEOUT: int = field(
        default_factory=get_env('KAFKA_GRACEFUL_SHUTDOWN_TIMEOUT', 5)
    )

    # kafka connection
    KAFKA_BOOTSTRAP_SERVERS: str = field(
        default_factory=get_env('KAFKA_BOOTSTRAP_SERVERS', 'localhost:29092')
    )
    KAFKA_CONSUMER_GROUP_ID: str = field(
        default_factory=get_env('KAFKA_CONSUMER_GROUP_ID', 'eworksuite-worker-group')
    )
    KAFKA_MESSAGE_CONSUMING_FROM_BEGINING: bool = field(
        default_factory=get_env('KAFKA_MESSAGE_CONSUMING_FROM_BEGINING', False, bool)
    )
    """
    only triggers when a consumer group has no committed offset (e.g., a new consumer group starting for the first time)
    or when its committed offset has expired/been deleted due to log retention policies.
      - True: consume messages from the beginning of the topic (earliest offset), when use:
        + Core transaction processing
        + Financial ledgers & auditing
        + Event-sourcing architectures
        + ETL & Data warehousing
      - False: consume messages from the latest offset (default)
        + Real-time telemetry/metrics,
        + Live dashboards
        + Instant alert notifications
        + Ephemeral cache warmups

    """

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

    # kafka reconnect / retry pacing
    #
    # aiokafka retries a failed metadata refresh or connection as fast as this
    # backoff allows, logging one ERROR per attempt. Its own default of 100ms
    # produces thousands of lines a minute while a broker is down, so the
    # default here is deliberately far slower.
    KAFKA_RETRY_BACKOFF_MS: int = field(
        default_factory=get_env('KAFKA_RETRY_BACKOFF_MS', 1_000)
    )
    """Backoff between connection/metadata retry attempts (aiokafka default: 100)."""

    KAFKA_METADATA_MAX_AGE_MS: int = field(
        default_factory=get_env('KAFKA_METADATA_MAX_AGE_MS', 300_000)
    )
    """Forced metadata refresh interval even when no fault is detected."""

    KAFKA_REQUEST_TIMEOUT_MS: int = field(
        default_factory=get_env('KAFKA_REQUEST_TIMEOUT_MS', 40_000)
    )
    """Per-request timeout handed to the aiokafka client."""

    # kafka client log throttling
    KAFKA_LOG_THROTTLE_ENABLED: bool = field(
        default_factory=get_env('KAFKA_LOG_THROTTLE_ENABLED', True, bool)
    )
    """Collapse repeated aiokafka retry ERRORs into a periodic summary line."""

    KAFKA_LOG_THROTTLE_BURST: int = field(
        default_factory=get_env('KAFKA_LOG_THROTTLE_BURST', 1)
    )
    """Identical aiokafka records to emit before suppression starts (per message)."""

    KAFKA_LOG_THROTTLE_INTERVAL_S: int = field(
        default_factory=get_env('KAFKA_LOG_THROTTLE_INTERVAL_S', 60)
    )
    """Seconds between suppressed-summary lines while a fault persists."""

    # kafka security
    #
    # PROTOCOL sets the transport (is it TLS? is anyone authenticated?);
    # MECHANISM sets which credential the SASL handshake carries. Both are
    # needed for SASL_* listeners — see MessagingConfig for the full matrix.
    KAFKA_SECURITY_PROTOCOL: str | None = field(
        default_factory=get_env('KAFKA_SECURITY_PROTOCOL', None, str)
    )
    """
    ``PLAINTEXT`` (default) | ``SSL`` | ``SASL_PLAINTEXT`` | ``SASL_SSL``.

    Must match the broker listener being dialed. Anything with ``SSL`` is
    TLS-wrapped; anything with ``SASL`` runs an authentication handshake.
    """
    KAFKA_SASL_MECHANISM: str | None = field(
        default_factory=get_env('KAFKA_SASL_MECHANISM', None, str)
    )
    """
    ``PLAIN`` | ``SCRAM-SHA-256`` | ``SCRAM-SHA-512`` | ``GSSAPI`` | ``OAUTHBEARER``.

    Required when ``KAFKA_SECURITY_PROTOCOL`` starts with ``SASL_``, and rejected
    otherwise — a mechanism without a SASL protocol is a silently ignored
    credential. Note FastStream supports only ``PLAIN`` and the ``SCRAM-*`` pair.
    """
    KAFKA_SASL_USERNAME: str | None = field(
        default_factory=get_env('KAFKA_SASL_USERNAME', None, str)
    )
    """SASL identity. Required for ``PLAIN`` and ``SCRAM-*``; unused by GSSAPI/OAUTHBEARER."""
    KAFKA_SASL_PASSWORD: str | None = field(
        default_factory=get_env('KAFKA_SASL_PASSWORD', None, str)
    )
    """SASL secret. Required for ``PLAIN`` and ``SCRAM-*``; unused by GSSAPI/OAUTHBEARER."""
    KAFKA_SSL_CA_LOCATION: str | None = field(
        default_factory=get_env('KAFKA_SSL_CA_LOCATION', None, str)
    )
    """
    Path to the PEM CA bundle that signed the broker certificate. Preferred when
    the CA is mounted as a file; takes precedence over ``KAFKA_CA_DATA``.
    """
    KAFKA_CA_DATA: str | None = field(
        default_factory=get_env('KAFKA_CA_DATA', None, str)
    )
    """
    Inline CA bundle, for deployments that inject the cert as a variable rather
    than mounting a file (K8s secrets, CI/CD, PaaS). Accepts multi-line PEM,
    single-line PEM with ``\\n`` escapes, or base64-encoded PEM.
    Ignored when ``KAFKA_SSL_CA_LOCATION`` is set.
    """
    KAFKA_SSL_CHECK_HOSTNAME: bool = field(
        default_factory=get_env('KAFKA_SSL_CHECK_HOSTNAME', True, bool)
    )
    """
    Verify the broker certificate matches the hostname dialed. ``false`` still
    verifies the chain but trusts any host the CA signed — dev only.
    """
    KAFKA_SSL_STRICT_VERIFY: bool = field(
        default_factory=get_env('KAFKA_SSL_STRICT_VERIFY', True, bool)
    )
    """
    Apply RFC 5280 strict checks (Python 3.13+ default). Set ``false`` for
    private CAs lacking a ``keyUsage`` extension, e.g. a Strimzi cluster CA.
    """

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

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        """Split ``kafka_bootstrap_servers`` into a list."""
        return [s.strip() for s in self.KAFKA_BOOTSTRAP_SERVERS.split(',') if s.strip()]
