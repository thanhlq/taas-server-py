from __future__ import annotations

from typing import Optional

from faststream.security import (
    BaseSecurity,
    SASLPlaintext,
    SASLScram256,
    SASLScram512,
)
from foundation.messaging.kafka.kafka_security import KafkaSecurityConfig

# SASL mechanism name (as configured for Kafka) → FastStream security class.
_SASL_MECHANISMS = {
    'PLAIN': SASLPlaintext,
    'SCRAM-SHA-256': SASLScram256,
    'SCRAM-SHA-512': SASLScram512,
}


def build_faststream_broker_security(
    cfg: KafkaSecurityConfig,
) -> Optional[BaseSecurity]:
    """
    Translate the messaging config into a FastStream security object.

    FastStream wraps SASL/TLS in a ``BaseSecurity`` subclass instead of the
    raw aiokafka kwargs; ``None`` means an unauthenticated PLAINTEXT broker.

    ``MessagingConfig`` has already normalized and cross-validated the
    protocol/mechanism pair, so this only has to dispatch on them.
    """
    if not (cfg.ssl_enabled or cfg.sasl_enabled):
        return None

    ssl_context = cfg.build_kafka_ssl_context()

    if not cfg.sasl_enabled:
        return BaseSecurity(ssl_context=ssl_context, use_ssl=cfg.ssl_enabled)

    # Config-level validation accepts every mechanism aiokafka supports;
    # FastStream ships wrappers for only a subset of them.
    sasl_class = _SASL_MECHANISMS.get(cfg.sasl_mechanism or '')
    if sasl_class is None:
        raise ValueError(
            f'Unsupported KAFKA_SASL_MECHANISM={cfg.sasl_mechanism!r} for '
            f'the FastStream provider; supported: {sorted(_SASL_MECHANISMS)}'
        )
    return sasl_class(
        username=cfg.sasl_username or '',
        password=cfg.sasl_password or '',
        ssl_context=ssl_context,
        use_ssl=cfg.ssl_enabled,
    )
