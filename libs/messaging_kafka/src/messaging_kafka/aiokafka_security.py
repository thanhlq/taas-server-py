from typing import Any

from foundation.messaging.kafka.kafka_security import KafkaSecurityConfig


def get_aiokafka_security_kwargs(config: KafkaSecurityConfig) -> dict[str, Any]:
    """Build aiokafka security kwargs from the shared messaging config.

    Mirrors :meth:`core.messaging.faststream.helper.FastStreamHelper.get_faststream_security`
    but returns plain ``aiokafka`` client kwargs instead of a FastStream
    ``BaseSecurity`` object.
    """

    if config.ssl_enabled:
        ssl_context = config.build_kafka_ssl_context()
    else:
        ssl_context = None

    kw: dict[str, Any] = {}
    if config.ssl_enabled:
        kw['security_protocol'] = 'SASL_SSL' if config.ssl_enabled else 'SASL_PLAINTEXT'
        kw['sasl_mechanism'] = 'PLAIN'
        kw['sasl_plain_username'] = config.sasl_username
        kw['sasl_plain_password'] = config.sasl_password
        kw['ssl_context'] = ssl_context
    return kw
