"""
Shared pytest fixtures for messaging_faststream tests.

Run all tests with:
    uv run pytest libs/messaging_faststream/tests/ -v

Run with coverage:
    uv run pytest libs/messaging_faststream/tests/ --cov=messaging_faststream -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup — ensure core and messaging_faststream src are importable
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).parent.parent.parent.parent
_core_src = _repo_root / 'libs' / 'core' / 'src'
_fs_src = Path(__file__).parent.parent / 'src'

for _p in (_core_src, _fs_src):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Singleton reset — FastStreamKafkaMessagingService and MsgEncoder are
# decorated with @singleton, so the same instance is returned across tests.
# Without resetting, mock-config patches in later tests have no effect.
# ---------------------------------------------------------------------------


def _reset_singletons() -> None:
    """Clear cached singleton instances of services that tests reconstruct."""
    from core.common import singleton as _singleton_mod  # noqa: F401

    for fn_qualname in (
        'messaging_faststream.faststream_aiokafka_impl.FastStreamKafkaMessagingService',
        'core.messaging.utils.msg_encoder.MsgEncoder',
    ):
        mod_name, _, cls_name = fn_qualname.rpartition('.')
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            get_instance = getattr(mod, cls_name, None)
            if get_instance is None or not getattr(get_instance, '__closure__', None):
                continue
            for cell in get_instance.__closure__:
                if isinstance(cell.cell_contents, dict):
                    cell.cell_contents.clear()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _isolate_singletons():
    """Reset @singleton-cached services before each test for isolation."""
    _reset_singletons()
    yield
    _reset_singletons()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_config(
    *,
    topics: list[str] | None = None,
    bootstrap_servers: str = 'localhost:9092',
    consumer_enable: bool = True,
    encoding: str = 'msgpack',
    dlq_enable: bool = False,
) -> MagicMock:
    """Build a mock ``AppSetting`` object for use in unit tests.

    Note: ``encoding`` defaults to ``msgpack`` so tests exercise the real
    ``MsgEncoder.msgpack_pack`` / ``msgpack_unpack`` round-trip used in
    production. Pass ``encoding='json'`` for JSON-only tests.
    """
    config = MagicMock()
    config.CONSUMER_TOPICS = topics or ['test.events']
    config.KAFKA_BOOTSTRAP_SERVERS = bootstrap_servers
    config.kafka_bootstrap_servers_list = [bootstrap_servers]
    config.KAFKA_CONSUMER_GROUP_ID = 'test-group'
    config.KAFKA_AUTO_OFFSET_RESET = 'earliest'
    config.KAFKA_ENABLE_AUTO_COMMIT = False
    config.CONSUMER_ENABLE = consumer_enable
    config.MAX_CONCURRENT_TASKS = 5
    config.GRACEFUL_SHUTDOWN_TIMEOUT = 5
    config.MAX_RETRIES = 3
    config.RETRY_BACKOFF_MS = 100
    config.DLQ_TOPIC = 'dlq.events'
    config.DLQ_ENABLE = dlq_enable
    config.MESSAGE_ENCODING = encoding
    config.MESSAGE_FIELD_ENCODING = 'msgpack'
    config.PUBSUB_SERVICE_PROVIDER = 'faststream-kafka'
    config.KAFKA_MAX_POLL_RECORDS = 500
    config.KAFKA_SESSION_TIMEOUT_MS = 30_000
    config.KAFKA_HEARTBEAT_INTERVAL_MS = 3_000
    config.KAFKA_SECURITY_PROTOCOL = None
    config.KAFKA_SASL_MECHANISM = None
    config.KAFKA_SASL_USERNAME = None
    config.KAFKA_SASL_PASSWORD = None
    config.OUTBOX_ENABLE = False
    config.OUTBOX_POLLER_ENABLE = False
    config.KAFKA_SCHEMA_REGISTRY_URL = ''
    config.KAFKA_SCHEMA_REGISTRY_USERNAME = None
    config.KAFKA_SCHEMA_REGISTRY_PASSWORD = None
    config.kafka_config = {
        'bootstrap_servers': [bootstrap_servers],
        'group_id': 'test-group',
        'auto_offset_reset': 'earliest',
        'enable_auto_commit': False,
    }
    return config


def make_base_event(
    event_type: str = 'test.event',
    payload: dict | None = None,
) -> Any:
    """Return a minimal ``BaseEvent`` for use in tests."""
    from core.events.types import BaseEvent

    event = BaseEvent(event_type=event_type, source='test-service')
    return event
