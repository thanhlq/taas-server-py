import dataclasses
import datetime
import json
import logging
from logging import Logger
from typing import Any, Optional, Union, get_args, get_type_hints

import msgspec
from foundation.cli import cli
from foundation.messaging.config.messaging_config import MessagingConfig
from foundation.messaging.kafka.sr import SchemaRegistryEncoder
from foundation.messaging.types import (
    EVENT_META_SERIALIZER_FIELD,
    EVENT_PAYLOAD_FIELD,
    BaseEvent,
    BaseSendableMessage,
    DlqEvent,
    IMessageEncoder,
    MessageEncodingType,
    MessageFieldEncodingType,
)
from foundation.utils.singleton import singleton


class MsgDecoderError(Exception):
    """Custom exception for message decoding errors."""

    _debug: bool = False

    def __init__(self, message: str | None = None, error_code: str | None = None):
        super().__init__(f'💥 {message if message is not None else "An error occurred while decoding the message."}')
        self.error_code = error_code


@singleton
class MsgEncoder(IMessageEncoder):
    """
    A default message encoder/decoder that supports multiple encoding formats (JSON, MsgPack, Protobuf, Avro).
    The encoding format can be specified via the constructor or will default to the setting defined in App
    """

    _instance: 'MsgEncoder | None' = None
    _msg_encoding: str
    _field_encoding: str
    _logger: Logger | None = None
    _event_type_registry: dict[str, type[BaseEvent]] = {}

    _json_encoder: Optional[msgspec.json.Encoder] = None
    _json_decoder: Optional[msgspec.json.Decoder] = None
    _field_types_cache: dict[type, dict[str, Any]]

    # @staticmethod
    # def get() -> 'MsgEncoder':
    #     """Get the singleton instance of MsgEncoder."""
    #     if not MsgEncoder._instance:
    #         raise ValueError('MsgEncoder instance has not been initialized yet. Please create an instance of MsgEncoder before calling MsgEncoder.get().')
    #     return MsgEncoder._instance

    def __init__(
        self,
        msg_encoding: str | None = None,
        field_encoding: str | None = None,
        *,
        config: MessagingConfig | None = None,
    ):
        # Resolution order: explicit args > MessagingConfig > 'json' default.
        cfg_msg = config.message_encoding if config is not None else None
        cfg_field = config.message_field_encoding if config is not None else None
        self._field_types_cache = {}
        self._msg_encoding = msg_encoding or cfg_msg or 'json'

        if self._msg_encoding == MessageEncodingType.SCHEMA_REGISTRY_AVRO:
            self._field_encoding = field_encoding or cfg_field or 'json'
            if self._field_encoding not in (
                MessageEncodingType.MSGPACK,
                MessageEncodingType.JSON,
            ):
                raise ValueError(
                    f'Unsupported field encoding "{self._field_encoding}" for Avro message encoding. Supported field encodings are: msgpack, json.'
                )
        else:
            self._field_encoding = (
                MessageFieldEncodingType.NA
            )  # Not applicable for non-Avro encodings

        startup_info: dict[str, Any] = self.info()
        cli.info_table('MsgEncoder startup info', startup_info)

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    def info(self) -> dict[str, Any]:
        return {
            'msg_encoding': self._msg_encoding,
            'field_encoding': self._field_encoding,
            'event_type_registry': {
                k: v.__name__ for k, v in self._event_type_registry.items()
            },
        }

    def msgpack_pack(self, data: Any) -> bytes:
        return msgspec.msgpack.encode(data)

    def msgpack_unpack(self, data: bytes) -> Any:
        return msgspec.msgpack.decode(data)

    def json_encode(self, data: Any) -> bytes:
        if self._json_encoder is None:
            self._json_encoder = msgspec.json.Encoder()
        return self._json_encoder.encode(data)

    def json_decode(self, data: str) -> Any:
        if self._json_decoder is None:
            self._json_decoder = msgspec.json.Decoder()
        return self._json_decoder.decode(data)

    def get_serializer_name(self, cls: type[BaseEvent]) -> str:
        # Important: EVENT_META_SERIALIZER_FIELD
        return f'{cls.__name__.lower()}_serializer'

    def register_event_serializer(
        self, cls: type[BaseEvent], serializer: Optional[str] = None
    ) -> 'IMessageEncoder':
        name = serializer or self.get_serializer_name(cls)
        self._event_type_registry[name] = cls
        self.logger.debug(
            f'🎯 ▶ Registered event clss serializer: "{name}" → {cls.__name__}'
        )
        return self

    def _get_field_types(self, cls: type) -> dict[str, Any]:
        """Resolve and cache type hints for a dataclass event subclass."""
        cached = self._field_types_cache.get(cls)
        if cached is not None:
            return cached
        try:
            hints = get_type_hints(cls)
        except Exception:
            # Fallback when forward references cannot be resolved
            hints = {f.name: f.type for f in dataclasses.fields(cls)}
        self._field_types_cache[cls] = hints
        return hints

    @staticmethod
    def _is_datetime_type(tp: Any) -> bool:
        """Return True for ``datetime.datetime`` and Optional/Union variants of it."""
        if tp is datetime.datetime:
            return True
        return any(arg is datetime.datetime for arg in get_args(tp))

    def reconstruct_event(self, event_data: Any) -> BaseSendableMessage:
        if not isinstance(event_data, dict):
            return event_data

        _serializer = event_data.get(EVENT_META_SERIALIZER_FIELD)
        if _serializer is None:
            self.logger.warning(
                'No serializer field found in event data, defaulting to BaseEvent. '
                'If you are seeing this message, it likely means the event was encoded without registering its serializer, or the serializer field was not included in the encoded data. '
                'To fix this, ensure that you register the event class with MsgEncoder.register_event_serializer() and that the serializer name is included in the event metadata when encoding.'
            )
            return event_data

        event_cls = (
            self._event_type_registry.get(_serializer, BaseEvent)
            if _serializer
            else BaseEvent
        )
        self.logger.debug(
            f'🎯 ⬅ Got event clss serializer: "{_serializer}" → {event_cls.__name__}'
        )
        field_types = self._get_field_types(event_cls)
        valid_fields = set(field_types)

        unknown = [k for k in event_data if k not in valid_fields]
        if unknown:
            self.logger.warning(
                f'Ignoring unknown field(s) {sorted(unknown)} when reconstructing '
                f'{event_cls.__name__} (serializer={_serializer!r})'
            )

        filtered: dict[str, Any] = {}
        for name, value in event_data.items():
            if name not in valid_fields:
                continue
            if isinstance(value, str) and self._is_datetime_type(field_types.get(name)):
                try:
                    value = datetime.datetime.fromisoformat(value)
                except ValueError:
                    self.logger.warning(
                        f'Failed to parse {name!r} as datetime on '
                        f'{event_cls.__name__}: {value!r}; leaving as string'
                    )
            filtered[name] = value

        return event_cls(**filtered)

    def __str__(self) -> str:
        return f'MsgEncoder(encoding={self._msg_encoding}, field_encoding={self._field_encoding})'

    def msg_encoding(self) -> str:
        return self._msg_encoding

    def field_encoding(self) -> str:
        return self._field_encoding

    async def encode_msg(
        self,
        msg: BaseSendableMessage,
        *,
        channel: str | None = None,
        sr_encoder: 'SchemaRegistryEncoder | None' = None,
    ) -> Union[bytes, str, Any]:
        """
        Encode a BaseEvent into the configured message format.

        Args:
            - msg:
                + The event that normally inherits from BaseEvent or DlqEvent to encode.
                + When msg is went thro the outbox service, it can be a dict that contains the event data.
            - channel: The channel to which the event will be sent (required for Avro encoding).
            - sr_encoder: An instance of AsyncSchemaRegistryEncoder (required for Avro encoding).
        """

        # Check if list -> batch encode each item in the list and return a list of encoded messages
        if isinstance(msg, list):
            return [
                await self.encode_msg(m, channel=channel, sr_encoder=sr_encoder)
                for m in msg
            ]

        # Check if is BaseEvent or subclass of BaseEvent, dlq event or dict, otherwise raise error
        if isinstance(msg, BaseEvent) or isinstance(msg, DlqEvent):
            _msg_data = msg.as_dict()
        else:
            _msg_data = msg

        if self._msg_encoding == MessageEncodingType.MSGPACK:
            return self.msgpack_pack(_msg_data)
        elif self._msg_encoding == MessageEncodingType.PROTOBUF:
            raise NotImplementedError('Protobuf encoding is not implemented yet.')
        elif self._msg_encoding == MessageEncodingType.SCHEMA_REGISTRY_AVRO:
            if not sr_encoder or not channel:
                raise ValueError(
                    'AsyncSchemaRegistryEncoder and channel are required for Avro encoding'
                )

            # check data is dict and if payload field exists
            if isinstance(_msg_data, dict):
                _event_payload = _msg_data.get(EVENT_PAYLOAD_FIELD, None)
                if _event_payload is not None and isinstance(_event_payload, dict):
                    _msg_data[EVENT_PAYLOAD_FIELD] = self.encode_field(_event_payload)
                else:
                    pass  # leave payload absent
            else:
                # Supported serialization formats
                pass

            return await sr_encoder.encode_event(channel, _msg_data)
        elif self._msg_encoding == MessageEncodingType.JSON:
            # JSON: return bytes for parity with msgpack/Avro and so brokers
            # (which expect bytes) don't need a separate encoding step.
            return self.json_encode(_msg_data)
        else:
            raise ValueError(f'Unsupported message encoding: {self._msg_encoding}')

    async def decode_msg(
        self,
        val: Any,
        channel: str | None = None,
        sr_encoder: 'SchemaRegistryEncoder | None' = None,
    ) -> BaseSendableMessage:
        if self._msg_encoding == MessageEncodingType.MSGPACK:
            try:
                all_data = self.msgpack_unpack(val)
                # all_data = _normalise_wire_data(unpacked_data)
                return self.reconstruct_event(all_data)
            except Exception as e:
                raise MsgDecoderError(
                    f'Failed to decode msgpack data: {e}',
                    error_code='MSGPACK_DECODE_ERROR',
                )
        elif self._msg_encoding == MessageEncodingType.PROTOBUF:
            raise NotImplementedError('Protobuf decoding is not implemented yet.')
        elif self._msg_encoding == MessageEncodingType.SCHEMA_REGISTRY_AVRO:
            if not sr_encoder or not channel:
                raise ValueError(
                    'AsyncSchemaRegistryEncoder and channel are required for Avro decoding'
                )
            try:
                _decoded_dict = await sr_encoder.decode(channel, val)
                _payload = _decoded_dict.get(EVENT_PAYLOAD_FIELD, None)
                if (
                    _payload is not None
                ) and self._field_encoding == MessageEncodingType.MSGPACK:
                    # If the payload is bytes and field encoding is msgpack, deserialize it back to dict after Avro decoding
                    if isinstance(_payload, bytes):
                        _decoded_dict[EVENT_PAYLOAD_FIELD] = self.msgpack_unpack(
                            _payload
                        )
                    elif isinstance(_payload, str):
                        self.logger.warning(
                            'Expected payload to be bytes for MsgPack field encoding, got str. Attempting to decode string payload as MsgPack bytes.'
                        )
                        try:
                            self.logger.debug(
                                f'Attempting to decode string payload as MsgPack bytes: {_payload}'
                            )
                            _decoded_dict[EVENT_PAYLOAD_FIELD] = self.msgpack_unpack(
                                _payload.encode('utf-8')
                            )
                        except Exception as e:
                            self.logger.error(
                                f'Failed to decode string payload as MsgPack bytes: {e}. Leaving payload as original string.'
                            )
                            _decoded_dict[EVENT_PAYLOAD_FIELD] = _payload
                elif (
                    _payload is not None
                ) and self._field_encoding == MessageEncodingType.JSON:
                    # If the payload is a string and field encoding is json, deserialize it back to dict after Avro decoding
                    if isinstance(_payload, str):
                        _decoded_dict[EVENT_PAYLOAD_FIELD] = json.loads(_payload)
                    elif isinstance(_payload, bytes):
                        _decoded_dict[EVENT_PAYLOAD_FIELD] = json.loads(
                            _payload.decode('utf-8')
                        )
                    else:
                        self.logger.warning(
                            f'Expected payload to be str or bytes for JSON field encoding, got {type(_payload)}. Leaving payload as is.'
                        )

                elif _payload is not None:
                    # Payload can be supported formats
                    raise ValueError(
                        f'Unsupported field encoding "{self._field_encoding}" for Avro message encoding. Supported field encodings are: msgpack, json.'
                    )

                # all_data = self.deserialize_bytes_fields_to_dict(decoded_dict)
                return self.reconstruct_event(_decoded_dict)
            except Exception as e:
                raise MsgDecoderError(
                    f'Failed to decode Avro data: {e}', error_code='AVRO_DECODE_ERROR'
                )
        elif self._msg_encoding == MessageEncodingType.JSON:
            # Default to JSON decoding
            try:
                if isinstance(val, bytes):
                    val = val.decode('utf-8')

                if not isinstance(val, str):
                    raise MsgDecoderError(
                        f'Expected string or bytes for JSON decoding, got {type(val)}',
                        error_code='INVALID_JSON_INPUT_TYPE',
                    )

                all_data = self.json_decode(val)

                return self.reconstruct_event(all_data)
            except json.JSONDecodeError as e:
                raise MsgDecoderError(
                    f'Failed to decode JSON data: {e}', error_code='JSON_DECODE_ERROR'
                )
        else:
            raise ValueError(f'Unsupported message encoding: {self._msg_encoding}')

    def encode_field(self, payload: BaseSendableMessage) -> Union[bytes, str, Any]:
        if self._msg_encoding != MessageEncodingType.SCHEMA_REGISTRY_AVRO:
            raise ValueError(
                f'Field encoding is only applicable for Avro message encoding. Current message encoding: {self._msg_encoding}'
            )

        _field_data = payload

        if dataclasses.is_dataclass(payload):
            if getattr(payload, 'as_dict', None) and callable(payload.as_dict):  # type: ignore
                _field_data = payload.as_dict()  # type: ignore
            else:
                _field_data = dataclasses.asdict(payload)  # type: ignore

        if self._field_encoding == MessageFieldEncodingType.JSON:
            return self.json_encode(_field_data)
        elif self._field_encoding == MessageFieldEncodingType.MSGPACK:
            return self.msgpack_pack(_field_data)
        else:
            raise ValueError(
                f'Unsupported field encoding "{self._field_encoding}" for Avro message encoding. Supported field encodings are: msgpack, json.'
            )

    def decode_field(self, val: Any) -> dict:
        if self._msg_encoding != MessageEncodingType.SCHEMA_REGISTRY_AVRO:
            raise ValueError(
                f'Field decoding is only applicable for Avro message encoding. Current message encoding: {self._msg_encoding}'
            )

        if self._field_encoding == MessageFieldEncodingType.JSON:
            return self.json_decode(val)
        elif self._field_encoding == MessageFieldEncodingType.MSGPACK:
            return self.msgpack_unpack(val)
        else:
            raise ValueError(
                f'Unsupported field encoding "{self._field_encoding}" for Avro message encoding. Supported field encodings are: msgpack, json.'
            )
