from dataclasses import dataclass, field

from foundation.utils.env_utils import get_env


@dataclass
class MessagingSettings:
    """Common settings for messaging services."""

    # encoding
    MESSAGE_ENCODING: str = field(
        default_factory=get_env('MESSAGE_ENCODING', 'msgpack')
    )
    MESSAGE_FIELD_ENCODING: str = field(
        default_factory=get_env('MESSAGE_FIELD_ENCODING', 'msgpack')
    )

    MESSAGING_DEBUG: bool = field(default_factory=get_env('MESSAGING_DEBUG', False, bool))

    # provider
    PROVIDER_TYPE: str = field(default_factory=get_env('PROVIDER_TYPE', 'kafka'))

    # retry / DLQ
    RETRY_MAX_RETRIES: int = field(default_factory=get_env('MAX_RETRIES', 3))
    RETRY_BACKOFF_MS: int = field(default_factory=get_env('RETRY_BACKOFF_MS', 1000))
    DLQ_ENABLED: bool = field(default_factory=get_env('DLQ_ENABLED', True, bool))
    DLQ_TOPIC: str = field(default_factory=get_env('DLQ_TOPIC', 'dlq.events'))

    CONSUMER_CHANNELS: list[str] = field(
        default_factory=get_env('CONSUMER_CHANNELS', [], list[str])
    )
    CHANNEL_CONSISTENCY_CHECK_ENABLED: bool = field(
        default_factory=get_env('CHANNEL_CONSISTENCY_CHECK_ENABLED', True, bool)
    )
    CONSUMER_ENABLED: bool = field(
        default_factory=get_env('CONSUMER_ENABLED', True, bool)
    )
    CONSUMER_GROUP_ID: str = field(
        default_factory=get_env('CONSUMER_GROUP_ID', 'messaging-service')
    )

    # outbox
    OUTBOX_ENABLE: bool = field(default_factory=get_env('OUTBOX_ENABLE', False, bool))
    OUTBOX_POLLER_ENABLE: bool = field(
        default_factory=get_env('OUTBOX_POLLER_ENABLE', False, bool)
    )
