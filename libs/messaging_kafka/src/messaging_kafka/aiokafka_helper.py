"""
Specialized helper functions for working with aiokafka.
"""
from typing import Sequence

import json

from aiokafka import ConsumerRecord
from core.events.types import BaseEvent
from core.observability.log_factory import LogFactory


def print_kafka_headers(headers: Sequence[tuple[bytes, bytes]]) -> None:
    for key, value in headers:
        print(f' Header: {key.decode("utf-8")}: {value.decode("utf-8")}')


class AiokafkaHelper:
    @staticmethod
    def find_traceparent(message: ConsumerRecord) -> str | None:
        if not message.headers or len(message.headers) == 0:
            return None
        return AiokafkaHelper.find_traceparent_in_headers(message.headers)

    @staticmethod
    def find_traceparent_in_headers(headers: Sequence[tuple[str, bytes]]) -> str | None:
        # Sequence[tuple[str, bytes]]
        """ Extract traceparent from Kafka message headers for distributed tracing."""
        if headers:
            for header_key, header_value in headers:
                if 'traceparent' == header_key:
                    traceparent = header_value.decode('utf-8')
                    LogFactory().get_logger().debug(
                        f'👓 Extracted traceparent from Kafka message header: {traceparent}'
                    )
                    return traceparent
        return None

    @staticmethod
    def parse_event_from_message(message: ConsumerRecord) -> BaseEvent:
        if message.value is None:
            raise ValueError('Message value is None')
        raw_data = message.value.decode('utf-8')
        data = json.loads(raw_data)
        # Parse event
        event = BaseEvent(**data)
        return event

    @staticmethod
    def to_aiokafka_headers(
        headers: dict[str, str],
    ) -> list[tuple[str, bytes]]:
        return [
            (key, value.encode('utf-8'))
            for key, value in headers.items()
            if value is not None # type: ignore[union-attribute]
        ]

    # @staticmethod
    # def serialize_headers(headers: dict[str, str]) -> list[tuple[bytes, bytes]]:
    #     return [
    #         (key.encode('utf-8'), value.encode('utf-8'))
    #         for key, value in headers.items()
    #     ]

    # @staticmethod
    # def deserialize_headers(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    #     return {key.decode('utf-8'): value.decode('utf-8') for key, value in headers}

    @staticmethod
    def print_consumer_record(record: ConsumerRecord) -> None:
        print(
            f'ConsumerRecord(destination={record.topic}, partition={record.partition}, '
            f'offset={record.offset}, timestamp={record.timestamp}, '
            f'timestamp_type={record.timestamp_type}, key={record.key}, '
            f'value={record.value}, headers={record.headers})'
            f'traceparent={AiokafkaHelper.find_traceparent(record)}'
        )
