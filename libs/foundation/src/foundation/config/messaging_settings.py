"""Global messaging settings for the application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from foundation.utils.env_utils import get_env

MessagingAdapterType = Literal[
    'kafka', 'faststream-kafka', 'faststream-nats', 'faststream-mqtt', 'redis', 'sqs'
]


@dataclass
class MessagingSettings:
    """Email backend: console, memory, smtp, resend."""

    MESSAGING_ADAPTER: str = field(
        default_factory=get_env('MESSAGING_ADAPTER', 'faststream-kafka')
    )

    CONSUMER_ENABLE: bool = field(
        default_factory=get_env('MESSAGING_CONSUMER_ENABLE', True, bool)
    )

    def __post_init__(self):
        if self.MESSAGING_ADAPTER not in [
            'kafka',
            'faststream-kafka',
            'faststream-nats',
            'faststream-mqtt',
            'redis',
            'sqs',
        ]:
            raise ValueError(
                f'Invalid MESSAGING_ADAPTER: {self.MESSAGING_ADAPTER}. Must be one of: kafka, faststream-kafka, faststream-nats, faststream-mqtt, redis, sqs.'
            )
