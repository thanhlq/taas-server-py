import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    TypeAlias,
    TypeVar,
    Union,
    runtime_checkable,
)

import msgspec
from foundation import BaseService
from foundation.serialization import BaseModel
from foundation.utils import now_in_utc
from foundation.utils.id import generate_id
from foundation.utils.serialization import from_json

if TYPE_CHECKING:
    from ..messaging.sr import SchemaRegistryEncoder

try:
    from dataclasses_avroschema import AvroModel as _AvroModelBase
except ImportError:  # pragma: no cover – optional dep not installed in all envs
    _AvroModelBase = object  # type: ignore[assignment,misc]  # ty:ignore[invalid-assignment]


class EventStatus(StrEnum):
    """Event processing status."""

    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    RETRYING = 'retrying'
    DEAD_LETTER = 'dead_letter'


########################################################################################################################
# Payload, why bytes:
#   - Avro model supports bytes
#   - bytes can be easily converted by msgpack/avro serializers without worrying about encoding issues
########################################################################################################################
type EventPayloadType = bytes | str | dict | None
"""
Event payload can be in one of several formats depending on the serialization method used,

Serialization:
    - the type MUST be bytes or str for serialization to work correctly (e.g. Avro does not support dicts directly, JSON does not support bytes directly)


    - bytes: Avro-encoded bytes (if using Avro serialization) or msgpack-encoded bytes (if using msgpack serialization)
    - str: JSON-serialised dict (if using JSON serialization)
    - dict: Already deserialised dict (if accessed programmatically after deserialization)
    - None: Not set
"""

T = TypeVar('T')
EVENT_META_SERIALIZER_FIELD = 'm_serializer'
EVENT_PAYLOAD_FIELD = 'payload'


class DlqEvent(
    msgspec.Struct,
    _AvroModelBase,  #  # pyright: ignore[reportUntypedBaseClass, reportGeneralTypeIssues]
):
    """Event structure for messages sent to Dead Letter Queue (DLQ)."""

    original_event: dict[str, Any]
    error: str
    failed_at: datetime = field(default_factory=now_in_utc)
    retry_count: int = field(default=0)
    handler_name: Optional[str] = field(
        default=None,
    )

    def __post_init__(self) -> None:
        # Optional: manual validation since dataclasses don't validate
        if self.retry_count < 0:
            raise ValueError('retry_count must be >= 0')

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the DLQ event."""
        return {
            'original_event': self.original_event,
            'error': self.error,
            'failed_at': self.failed_at.isoformat(),
            'retry_count': self.retry_count,
            'handler_name': self.handler_name,
        }


class BaseEvent(msgspec.Struct, _AvroModelBase):  # pyright: ignore[reportUntypedBaseClass, reportGeneralTypeIssues]
    """
    Flat event structure with all metadata fields inline.

    Inherits from AvroModel (when available) for native Avro schema generation.
    Domain-specific events should subclass this and add their own fields.

    The ``metadata`` property provides backward-compatible access to an
    ``EventMetadata`` view of the flat fields so existing handler code that
    references ``event.metadata.event_type`` continues to work unchanged.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.m_serializer = f'{cls.__name__.lower()}_serializer'

    ########################################################################################################################
    # Metadata fields (common to all events)
    ########################################################################################################################
    event_type: str
    event_id: str = field(default_factory=generate_id)
    timestamp: datetime = field(default_factory=now_in_utc)
    retry_count: int = 0
    m_serializer: str = 'baseevent_serializer'
    handler_name: Optional[str] = None
    """ Failure handler name for retry/dead-letter scenarios - populated by event processor at runtime, not set by event publishers """
    source: Optional[str] = None
    """
        Event source service - optional field that can be set by publishers for additional context, not used by event processor logic but may be useful for monitoring and debugging
        Examples: 'iam-service', 'billing-service', 'user-service', etc.
    """
    destination: Optional[str] = None
    """ Event destination service - optional field that can be set by publishers for additional context, not used by event processor logic but may be useful for monitoring and debugging
        Examples: 'iam-service', 'billing-service', 'user-service', etc.
    """

    user_id: Optional[str] = None
    tenant_id: Optional[str] = None

    ########################################################################################################################
    # Standard W3C Trace Context fields
    ########################################################################################################################
    # traceparent: Optional[str] = None
    # tracestate
    # correlation_id: Optional[str] = None

    ########################################################################################################################
    # Domain-specific payload fields (defined by subclasses)
    # bytes | str: avro compatible types for payload
    ########################################################################################################################
    payload: bytes | str | None = None

    def __post_init__(self) -> None:
        self.m_serializer = type(self).m_serializer
        if not self.event_id:
            self.event_id = generate_id()
        if not self.timestamp:
            self.timestamp = now_in_utc()

    def set_payload(self, payload: bytes | str | None):
        """Helper method to set the payload for good type hint."""
        self.payload = payload
        return self

    def _serialize(self, encoder: 'IMessageEncoder', **kwargs: Any) -> Any:
        """
        The hook method for serialization logic, called by the message service when serializing an event at runtime
        - The msg encoder only serializes the default "payload field" as bytes or str, and leaves the rest of the fields as-is

        Args:
            encoder: The message encoder instance that is performing the serialization, which may have additional context or

        Examples:
            - For Avro serialization, the payload must be bytes, so event publishers can override this method to encode it using the Avro schema
            - For JSON serialization, the payload must be str, so event publishers can override this method to encode it using json.dumps
        """

        return self  # No-op by default, can be overridden by subclasses for custom serialization logic

    def _deserialize(self, encoder: 'IMessageEncoder', **kwargs: Any) -> Any:
        """
        The hook method for deserialization logic, called by the message service when deserializing an event at runtime
        - The msg encoder only deserializes the default "payload field" as bytes or str, and leaves the rest of the fields as-is
        Examples:
            - For Avro serialization, the payload will be deserialized as bytes, and the event processor can override this method to decode it using the Avro schema
            - For JSON serialization, the payload will be deserialized as str, and the event processor can override this method to decode it using json.loads
        """

        return self  # No-op by default, can be overridden by subclasses for custom deserialization logic

    def payload_as_dict(self, p: bytes | str | None = None) -> Optional[dict[str, Any]]:
        """Helper method to get the payload as a dict, regardless of its original format."""

        val = p or self.payload
        if val is None:
            return None

        if isinstance(val, dict):
            return val
        elif isinstance(val, str):
            return from_json(val)
        else:
            #  Not decoded by message service correctly
            raise ValueError('Unsupported payload type')

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the event, including payload as dict if possible."""
        return msgspec.structs.asdict(self)  # type: ignore[reportGeneralTypeIssues]

    # def payload_as_object(
    #     self, cls: type[T], payload: Optional[dict[str, Any]] = None
    # ) -> Optional[T]:
    #     """Helper method to get the payload as an object of type cls, if possible."""
    #     payload_dict = payload or self.payload_as_dict()
    #     if payload_dict is None:
    #         return None
    #     return cls(**payload_dict)

    class Meta:
        namespace = 'com.eworksuite'


class StandardDataclass(Protocol):
    """Protocol to check type is dataclass."""

    __dataclass_fields__: ClassVar[dict[str, Any]]


JsonArray: TypeAlias = Sequence['DecodedMessage']

JsonTable: TypeAlias = dict[str, 'DecodedMessage']

JsonDecodable: TypeAlias = bool | bytes | bytearray | float | int | str | None

DecodedMessage: TypeAlias = JsonDecodable | JsonArray | JsonTable

SendableArray: TypeAlias = Sequence['BaseSendableMessage']

SendableTable: TypeAlias = dict[str, 'BaseSendableMessage']

BaseSendableMessage: TypeAlias = (
    JsonDecodable
    | Decimal
    | datetime
    | BaseEvent
    | StandardDataclass
    | SendableTable
    | SendableArray
    | None
)


@dataclass(frozen=True)
class MessageEncodingType:
    JSON: str = 'json'
    MSGPACK: str = 'msgpack'
    PROTOBUF: str = 'protobuf'
    # Pure avro binary encoding without schema registry (not recommended for production due to lack of
    # schema management, but can be useful for testing or simple use cases)
    # Without Schema Registry: the message size is bigger
    AVRO_BINARY: str = 'avro-binary'
    SCHEMA_REGISTRY_AVRO: str = 'schema-registry-avro'


@dataclass(frozen=True)
class MessageFieldEncodingType:
    NA: str = 'n/a'  # No additional encoding, the field will be stored as a JSON string in the Avro message
    JSON: str = 'json'
    MSGPACK: str = 'msgpack'


class MessageHandler(Protocol):
    """Protocol for message handlers."""

    async def __call__(self, message: Union[Dict[str, Any], BaseEvent]) -> None: ...


class MessagingType(str, Enum):
    """Enumeration of messaging service types."""

    PUBSUB = 'pubsub'
    STREAM = 'stream'
    QUEUE = 'queue'


class MessagingProvider(str, Enum):
    """Enumeration of supported pub/sub providers."""

    KAFKA_FASTSTREAM = 'faststream.aiokafka'
    """ Faststream by using aiokafka under the hood, with optimizations for high throughput and low latency. """
    KAFKA_AIOKAFKA = 'aiokafka'
    """
        Pure async Kafka client using aiokafka library. Suitable for high-throughput, low-latency
        applications.
    """
    SQS = 'sqs'
    REDIS = 'redis'
    NATS = 'nats'
    RABBITMQ = 'rabbitmq'


"""

TODO: TO only add the following fields

@dataclass(slots=True)
class MessageServiceStats:
    # Health (cheap to read, used by probes)
    is_connected: bool = False
    is_producer_ready: bool = False
    is_consumer_ready: bool = False
    last_error: Optional[str] = None

    # Runtime introspection (cheap, used by debug/admin endpoints)
    running: bool = False
    active_subscriptions: int = 0
    active_tasks: int = 0
    total_consumer_groups: int = 0

    provider: str = 'unknown'
"""


class MessageServiceStats(BaseModel):
    """
    Lightweight messaging service statistics for Kafka (producer + consumer).

    This dataclass uses slots=True for:
    - 40% less memory usage per instance
    - 10-20% faster attribute access
    - Type safety (no dynamic attributes)

    Supports dict-style access (stats['key']) for backward compatibility
    with EventProcessor and existing tests.
    """

    uptime_seconds: float
    requests_handled: int
    errors_occurred: int
    last_restart: Optional[datetime] = None

    # Producer counters (incremented on every publish call)
    messages_published: int = 0

    # Consumer counters (incremented per consumed message)
    messages_processed: int = 0  # successfully handled by a handler
    messages_failed: int = 0  # handler returned an error
    messages_retried: int = 0  # retried at least once
    messages_dlq: int = 0  # sent to the dead-letter queue

    # Resource counters (updated less frequently)
    total_channels: int = 0
    total_queues: int = 0
    total_streams: int = 0
    total_active_subscriptions: int = 0
    total_consumer_groups: int = 0

    # Performance metrics (sampled or calculated on-demand)
    avg_publish_latency_ms: float = 0.0
    avg_consume_latency_ms: float = 0.0
    messages_per_second: float = 0.0

    # Connection and health (cached, not real-time)
    is_connected: bool = False
    is_producer_ready: bool = False
    is_consumer_ready: bool = False
    connection_errors: int = 0
    last_error: Optional[str] = None

    # Consumer lag (refreshed periodically, e.g., every 30s)
    consumer_lag: int = 0
    oldest_message_age_seconds: Optional[float] = None

    # Runtime snapshot fields — set by get_stats(), not incremented
    running: bool = False
    active_tasks: int = 0
    active_subscriptions: int = 0

    # Additional provider-specific metadata
    provider: str = 'unknown'
    cluster_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # dict-style access — keeps EventProcessor and tests working as-is
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def keys(self) -> list[str]:
        """Return field names (mirrors dict.keys() behaviour)."""
        import dataclasses as _dc

        return [f.name for f in _dc.fields(self)]

    def copy(self) -> Dict[str, Any]:
        """Return a plain dict snapshot (mirrors dict.copy() behaviour)."""
        import dataclasses as _dc

        return _dc.asdict(self)


class IMessageEncoder(Protocol):
    """Protocol for message encoders."""

    def __init__(
        self,
        msg_encoding: str | None = None,
        field_encoding: str | None = None,
        *,
        config: Any = None,
    ): ...

    def register_event_serializer(
        self, cls: type[BaseEvent], serializer: Optional[str] = None
    ) -> 'IMessageEncoder': ...

    """
        This is used for registering the event class for a given serializer name.

        During deserialing of the event data into event class, this name will be used for picking the correct event class to deserialize into.


        Examples:

        ```python
        msg_encoder.register_event_serializer(UserRegisteredEvent, serializer='user-registered-event-serializer')

        cls = msg_encoder.get_event_class_for_serializer('user-registered-event-serializer')
        cls == UserRegisteredEvent  # True
        e = cls(**event_data)
    """

    @abstractmethod
    def reconstruct_event(self, event_data: Any) -> BaseSendableMessage: ...

    # def encode_msg(self, msg: dict | BaseEvent | DlqEvent) -> Union[bytes, str]: ...

    async def encode_msg(
        self,
        msg: BaseSendableMessage,
        *,
        channel: str | None = None,
        sr_encoder: 'SchemaRegistryEncoder | None' = None,
    ) -> Union[bytes, str, Any]: ...

    """
    Encode a full message (BaseEvent, DlqEvent, or dict) into bytes or string for transmission.
    """

    async def decode_msg(self, val: Any) -> BaseEvent | Any: ...

    """
        Decode a received message (bytes or string) back into a BaseEvent or dict.
    """

    def encode_field(self, payload: Any) -> Union[bytes, str]: ...

    """
        Encode the payload field of an event into bytes or string for serialization.
            - Normally used for specific fields which are additional to the "payload" field
            - Schema registry /Avro (schema-registry-avro):
                ✓ The field encoding can be used as: json, msgpack, or Avro binary encoding (bytes)
            - For JSON encoding (json):
                ✓ The field encoding can be used to convert complex objects (e.g., datetime) into JSON-serializable formats (e.g., ISO string).
            - For msgpack:
                ✓ The field encoding can be completely bypassed since msgpack can handle more complex types natively, but it can still be used for custom transformations if needed.
    """

    def decode_field(self, val: Any) -> dict: ...


class IMessagingService[M](BaseService, ABC):
    """
    Base messaging service interface.

    Generic type M:
        represents the native message type i.e. aiokafka's ConsumerRecord or SQS's Message.

    This interface defines the contract that all messaging services
    (pub/sub, streams, queues) must implement.

    Common lifecycle methods are defined here to avoid duplication
    across messaging patterns.

    Message Ordering and Delivery Guarantees:
    - Pub/Sub: At-least-once delivery, no ordering guarantees (unless using partitions/keys)
    - Streams: At-least-once delivery, ordering guaranteed within partitions
    - Queues: At-least-once delivery, optional FIFO ordering (depends on provider
    """

    @abstractmethod
    def is_consumer_enabled(self) -> bool:
        """Return True if the consumer is enabled and running."""
        ...

    @abstractmethod
    def get_msg_encoder(self) -> IMessageEncoder:
        """Get the message encoder used for serialization."""
        pass

    @abstractmethod
    def get_stats(self) -> MessageServiceStats:
        """Get comprehensive messaging service statistics."""
        pass

    @abstractmethod
    def get_provider(self) -> 'MessagingProvider':
        """Get the messaging provider type."""
        pass

    # @abstractmethod
    # async def astart(self) -> None:
    #     """
    #     Initialize and start the service based on configuration.
    #     This is a convenience method that may start producer, consumer, or both.
    #     """
    #     pass

    @abstractmethod
    async def start_producer(self) -> None:
        """Start producer for publishing messages."""
        pass

    @abstractmethod
    async def start_consumer(self) -> None:
        """Start consumer for receiving messages."""
        pass

    @abstractmethod
    async def start_consuming(self) -> None:
        """
        Start the message consumption loop (blocking operation).
        Process messages concurrently for higher throughput.
        """
        pass

    @abstractmethod
    async def start_consuming_sequential(self) -> None:
        """
        Start the message consumption loop (blocking operation).
        Process messages sequentially to preserve ordering and trace context.
        """
        pass

    @abstractmethod
    async def subscribe(
        self,
        channel: str,
        handler: MessageHandler,
        *,
        consumer_group: Optional[str] = None,
        from_beginning: bool = False,
        **kwargs,
    ) -> str:
        """
        Subscribe to channel with handler. Returns subscription ID.
        Args:
            channel: Name of the channel
            handler: Message handler function
            consumer_group: Consumer group ID (for coordinated consumption)
            from_beginning: If True, start from beginning; otherwise from latest

        Returns:
            Subscription ID
        """
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from channel/stream/queue using subscription ID."""
        pass

    @abstractmethod
    async def publish(
        self,
        channel: str,
        message: BaseEvent,
        *,
        key: bytes | str | Any | None = None,
        timestamp_ms: int | None = None,
        headers: dict[str, str] | None = None,
        partition: Optional[int] = None,
        correlation_id: str | None = None,
        reply_to: str = '',
        no_confirm: bool = False,
        **kwargs,
    ) -> asyncio.Future[M | None] | None:
        """
        Publish message to destination (channel/stream/queue).

        Args:
            channel: Target channel name (for pub/sub)
            message: Message to publish
            key: Optional key for message routing and ordering
            headers: Optional headers for the message
            partition: Optional partition for ordering (streams/channels)
            timestamp_ms:
                Epoch milliseconds (from Jan 1 1970 UTC) to use as
                the message timestamp. Defaults to current time.
            correlation_id: Optional correlation ID for request/response patterns
            reply_to: Optional reply-to channel for request/response patterns
            no_confirm: If True, do not wait for confirmation of message delivery

        Note:
            - For pub/sub: channel = channel name
            - For streams: channel = stream name, use partition for ordering
            - For queues: channel = queue name, use delay_seconds for delayed delivery
        """
        pass

    async def publish_batch(  # type: ignore[override]
        self,
        *messages: list[BaseEvent | dict],
        channel: str,
        partition: int | None = None,
        timestamp_ms: int | None = None,
        headers: dict[str, str] | None = None,
        reply_to: str = '',
        correlation_id: str | None = None,
        no_confirm: bool = False,
    ) -> None:
        pass

    @abstractmethod
    def register_schema(self, channel: str, schema: dict) -> str:
        """
        Register a schema for a channel/stream/queue. Returns schema ID.

        Args:
            channel: Channel name
            schema: Schema definition (e.g., Avro, Protobuf)
        Returns:
            Schema ID assigned by the registry
        """
        pass

    @abstractmethod
    def register_event_serializer(
        self, cls: type[BaseEvent], serializer: Optional[str] = None
    ) -> 'IMessagingService': ...

    """
        This is used for registering the event class for a given serializer name.

        During deserialing of the event data into event class, this name will be used for picking the correct event class to deserialize into.


        Examples:

        ```python
        msg_encoder.register_event_serializer(UserRegisteredEvent, serializer='user-registered-event-serializer')

        cls = msg_encoder.get_event_class_for_serializer('user-registered-event-serializer')
        cls == UserRegisteredEvent  # True
        e = cls(**event_data)
    """


@dataclass(slots=True)
class ChannelInfo:
    name: str
    is_internal: bool = False
    num_partitions: int = 0
    replication_factor: Optional[int] = None
    retention_hours: Optional[int] = None
    fifo: Optional[bool] = None
    partitions: Optional[List[dict[str, Any]]] = None  # List of partition info dicts
    metadata: Optional[dict[str, Any]] = None


class IMessagingAdminService(ABC):
    """
    Admin interface for messaging service management.

    This interface extends IMessagingService with additional administrative
    operations that may not be needed by all implementations but are useful
    for managing the messaging infrastructure.
    """

    @abstractmethod
    async def create_channel(
        self,
        channel: str,
        num_partitions: int = 1,
        *,
        replication_factor: int = 1,
        retention_hours: int = 168,  # 7 days default,
        fifo: bool = False,  # Only applicable for queues: if True, create FIFO queue with ordering guarantees.
        **kwargs,
    ) -> bool:
        """
        Create a new channel.

        Args:
            channel: Channel name
            num_partitions: Number of partitions (default: 1)
            replication_factor: Replication factor (default: 1)
            retention_hours: How long to retain messages (hours, default: 168)
            fifo: If True, create FIFO queue with ordering guarantees (only applicable for queues)
        """
        pass

    @abstractmethod
    async def delete_channel(self, channel: str) -> bool:
        """Delete a channel."""
        return False

    @abstractmethod
    async def list_channels(self) -> List[str]:
        """List all available channels."""
        pass

    @abstractmethod
    async def get_channel_info(self, channel: str) -> Optional[ChannelInfo]:
        """Get detailed information about a specific channel."""
        pass


# ============================================================================
# PUB/SUB SERVICE INTERFACE
# ============================================================================


class IMessagingPubSubService(IMessagingService, ABC):
    """
    Abstract pub/sub service interface:

    Delivery:
    - Publish messages to channels (1 -> N)
    - Subscribe to channels with handlers (N -> 1)
    - At-least-once delivery (normally deleted after successful processing)
    - Ordering not guaranteed unless using partitions/keys

    Providers:
    - Kafka, AWS SQS, Redis Pub/Sub, NATS (with JetStream for persistence), RabbitMQ, etc.
    - Small usages: In-memory or redis-based pub/sub for lightweight messaging

    Use cases:
    - Real-time notifications, event broadcasting

    For example: User registered → notify multiple services (email, analytics, CRM)
    """


class IMessagingStreamService(IMessagingService):
    """
    Abstract message stream service interface for log-based streaming.

    Delivery Model:
    - Messages are persisted and retained (not deleted after consumption)
    - Consumers track their own offset/position in the stream
    - Supports replay from any point in time
    - Multiple consumers can read independently (N -> N)

    Providers:
    - Kafka, AWS Kinesis, Azure Event Hubs, Apache Pulsar

    Use Cases:
    - Event sourcing (replay events)
    - Stream processing (real-time analytics)
    - Log aggregation (centralized logging)
    - Audit trails (immutable event log)

    Example: User activity stream consumed by multiple services independently
    """

    @abstractmethod
    async def create_stream(
        self,
        stream_name: str,
        num_partitions: int = 1,
        retention_hours: int = 168,  # 7 days default
    ) -> None:
        """
        Create a new stream.

        Args:
            stream_name: Name of the stream
            num_partitions: Number of partitions
            retention_hours: How long to retain messages (hours)
        """
        pass


# ============================================================================
# MESSAGE QUEUE SERVICE INTERFACE (Point-to-Point)
# ============================================================================


class IMessagingQueueService(IMessagingService):
    """
    Abstract message queue service interface for point-to-point messaging.

    Delivery Model:
    - Point-to-point (one consumer per message, message deleted after consumption)
    - At-least-once delivery (with acknowledgment)
    - Messages deleted after successful processing
    - Optional FIFO ordering guarantees

    Providers:
    - Kafka (with consumer groups), Redis (lists/streams), RabbitMQ, AWS SQS

    Use Cases:
    - Task distribution (one worker picks up the task)
    - Email/SMS sending (one sender processes the message)
    - Payment processing (exactly one processor)
    - Background jobs (job queues)

    Example: Email queue where only one worker sends each email

    Note: This interface is designed to be simple and consistent with IMessagingPubSubService.
    Advanced features like retries, DLQ, and idempotency should be handled by
    separate layers (middleware, outbox pattern, etc.)
    """


# ============================================================================
# DECORATOR INTERFACE (Faust-style ``@messaging.subscriber``)
# ============================================================================

#: Coroutine signature accepted by ``@subscriber``: ``handler(event, message)``.
#: ``event`` is the decoded :class:`~core.events.types.BaseEvent` (provider
#: specific), ``message`` is the provider's raw message wrapper (e.g.
#: ``faststream.kafka.KafkaMessage``, an aiokafka ``ConsumerRecord``, etc.).
type AgentHandler = Callable[..., Any]


@runtime_checkable
class IMessagingDecorators(Protocol):
    """Provider-agnostic decorator namespace exposed by a messaging backend.

    A backend implementation (FastStream, pure aiokafka, Redis Streams, ...)
    provides a singleton object that satisfies this Protocol so application
    code can stay decoupled from the concrete library:

    .. code-block:: python

        from core.messaging.types import IMessagingDecorators

        def register_agents(messaging: IMessagingDecorators) -> None:
            @messaging.subscriber(SharedTopics.SCOPE_TRACKER_EVENT)
            async def scope_tracker(event, message):
                ...

    Implementations are expected to:

    * Resolve the underlying messaging service lazily so modules using
      these decorators can be imported before the service is initialized.
    * Decode the raw payload into a ``BaseEvent`` (or domain object) via
      the service's configured :class:`IMessageEncoder` before invoking
      the user coroutine — handler code never sees raw bytes.
    * Route decode / handler exceptions through the project's error
      reporter (e.g. ``core.observability.error_reporter.report_error``)
      so failures reach tracing and APM instead of killing the consumer
      task.
    * Be idempotent: registering the same handler/topic twice MUST NOT
      create competing subscriptions in the same consumer group.
    """

    def subscriber(
        self,
        topic: str,
        *,
        group_id: Optional[str] = None,
        auto_offset_reset: Optional[Literal['latest', 'earliest', 'none']] = None,
    ) -> Callable[[AgentHandler], AgentHandler]:
        """Register the decorated coroutine as a subscriber for *topic*.

        Args:
            topic: Logical topic / stream / channel name to subscribe to.
            group_id: Override the consumer-group id. ``None`` means use
                the backend's configured default group.
            auto_offset_reset: Override the offset-reset policy for this
                subscription. ``None`` means use the backend default.

        Returns:
            A decorator that wraps the user coroutine. The returned
            coroutine is invoked as ``handler(event, message)`` for each
            successfully decoded incoming message.
        """
        ...

@dataclass
class ProcessingResult:
    """Result of event processing."""

    event_id: str
    success: bool | None = True
    message: str = 'Processed with OK status'
    retry_count: int = 0
    processing_time_ms: Optional[float] = 0
    error: Optional[str] = None
    handler_name: Optional[str] = None
