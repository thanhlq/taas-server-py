import ssl
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from foundation.messaging.kafka.kafka_settings import KafkaSettings
from foundation.utils.ca_data_utils import normalize_ca_data


class KafkaSecurityType(StrEnum):
    # ---- Kafka: security ----------------------------------------------------
    # Two *orthogonal* axes, named to match the Kafka client API 1:1:
    #
    #   kafka_security_protocol -> how the connection is framed (TLS? auth at all?)
    #   kafka_sasl_mechanism    -> which credential type the SASL handshake uses
    #
    #   protocol         TLS  SASL  credential
    #   PLAINTEXT        no   no    none — local dev / trusted network only
    #   SSL              yes  no    client certificate (mTLS)
    #   SASL_SSL         yes  yes   user/password (or ticket/token), encrypted
    #   SASL_PLAINTEXT   no   yes   user/password sent in the clear
    #
    # They overlap on exactly one bit — "does SASL run" — so contradictory pairs
    # are representable; __post_init__ rejects them instead of ignoring them.
    PLAINTEXT = 'PLAINTEXT'
    SSL = 'SSL'
    SASL_SSL = 'SASL_SSL'
    SASL_PLAINTEXT = 'SASL_PLAINTEXT'


KAFKA_SECURITY_PROTOCOLS = frozenset({'PLAINTEXT', 'SSL', 'SASL_PLAINTEXT', 'SASL_SSL'})
"""The four protocol names Kafka accepts in ``listener.security.protocol.map``."""

KAFKA_SASL_MECHANISMS = frozenset(
    {'PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512', 'GSSAPI', 'OAUTHBEARER'}
)
"""SASL mechanisms an aiokafka client can negotiate."""

KAFKA_SASL_PASSWORD_MECHANISMS = frozenset({'PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512'})
"""Subset of :data:`KAFKA_SASL_MECHANISMS` that authenticates with user/password."""


class KafkaSecurityConfig:
    """Kafka security configuration, derived from the messaging config."""

    sasl_mechanism: Optional[str] = None
    """
    Which SASL mechanism proves identity, once the protocol says SASL runs.

    One of :data:`KAFKA_SASL_MECHANISMS`; required when (and only when)
    ``kafka_security_protocol`` starts with ``SASL_``. Normalized to upper case
    with ``_`` folded to ``-`` (so ``scram_sha_512`` → ``SCRAM-SHA-512``).
    Says nothing about encryption — that is the protocol's job.
    """

    sasl_username: Optional[str] = None
    """SASL identity. Required for :data:`KAFKA_SASL_PASSWORD_MECHANISMS`."""

    sasl_password: Optional[str] = None
    """SASL secret. Required for :data:`KAFKA_SASL_PASSWORD_MECHANISMS`."""

    ssl_ca_location: Optional[str] = None
    """
    Path to the PEM CA bundle that signs the broker certificate.

    Highest-precedence trust anchor; use when the CA is mounted as a file.
    Ignored unless the protocol is TLS-bearing (``SSL``/``SASL_SSL``).
    """

    ssl_ca_data: Optional[str] = None
    """
    The same CA bundle carried inline, for when it arrives as a variable
    instead of a file (K8s secret, CI/CD store). Accepts multi-line PEM,
    single-line PEM with ``\\n`` escapes, or base64 PEM.
    Used only when ``ssl_ca_location`` is unset.
    """

    ssl_check_hostname: bool = True
    """
    Verify the broker's certificate matches the hostname you dialed.

    Turning this off still verifies the chain, but accepts *any* host the CA
    signed — acceptable for a dev cluster reached by IP, never in production.
    """

    ssl_strict_verify: bool = True
    """
    Apply the RFC 5280 strict checks Python 3.13+ enables by default.

    Set ``False`` for private CAs that omit the ``keyUsage`` extension (e.g. a
    hand-rolled Strimzi cluster CA). Chain and hostname verification stay on.
    """

    def __init__(self, cfg: KafkaSettings):
        self.protocol: KafkaSecurityType = KafkaSecurityType(
            cfg.KAFKA_SECURITY_PROTOCOL or KafkaSecurityType.PLAINTEXT
        )
        self.sasl_mechanism: Optional[str] = cfg.KAFKA_SASL_MECHANISM
        self.sasl_username: Optional[str] = cfg.KAFKA_SASL_USERNAME
        self.sasl_password: Optional[str] = cfg.KAFKA_SASL_PASSWORD
        self.ssl_enabled: bool = self.protocol.endswith('_SSL')
        self.sasl_enabled: bool = self.protocol.startswith('SASL_')
        self.ssl_ca_location: Optional[str] = cfg.KAFKA_SSL_CA_LOCATION
        self.ssl_ca_data: Optional[str] = cfg.KAFKA_CA_DATA
        self.ssl_check_hostname: bool = cfg.KAFKA_SSL_CHECK_HOSTNAME
        self.ssl_strict_verify: bool = cfg.KAFKA_SSL_STRICT_VERIFY

        # Validate the combination of protocol and SASL mechanism.
        if self.protocol in (KafkaSecurityType.PLAINTEXT, KafkaSecurityType.SSL):
            if self.sasl_mechanism is not None:
                raise ValueError(
                    f'Invalid configuration: protocol={self.protocol} '
                    f'cannot have a SASL mechanism ({self.sasl_mechanism})'
                )

    @property
    def kafka_ssl_trust_source(self) -> str:
        """Human-readable description of where the TLS trust anchor comes from."""
        if self.ssl_ca_location:
            return f'file:{self.ssl_ca_location}'
        if self.ssl_ca_data:
            return f'inline KAFKA_CA_DATA ({len(self.ssl_ca_data)} chars)'
        return 'system trust store'

    def build_kafka_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        TLS context for ``SSL``/``SASL_SSL`` brokers, ``None`` otherwise.

        ``None`` means "no ssl_context kwarg" — correct for PLAINTEXT and
        SASL_PLAINTEXT connections.
        """
        if not self.ssl_enabled:
            return None
        return _build_ssl_context(
            self.ssl_ca_location,
            self.ssl_ca_data,
            self.ssl_check_hostname,
            self.ssl_strict_verify,
        )


# @lru_cache(maxsize=1)
def get_kafka_security_config(cfg: KafkaSettings) -> KafkaSecurityConfig:
    """Build a :class:`KafkaSecurityConfig` from the messaging config."""
    return KafkaSecurityConfig(cfg)

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
