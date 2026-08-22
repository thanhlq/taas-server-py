"""``schema_registry_encoder_or_none`` must not raise for non-Avro encodings.

Regression cover for a total msgpack/json publish outage: ``_encode_message``
passed ``sr_encoder=self.schema_registry_encoder`` unconditionally, and that
property raises unless Avro is configured. Python evaluates call arguments
eagerly, so every publish failed with "Schema registry is not enabled" even
though the argument is unused outside Avro.
"""

from __future__ import annotations

import pytest

from foundation.messaging.types import MessageEncodingType


class _FakeMsgEncoder:
    def __init__(self, fmt: str) -> None:
        self.serialization_format = fmt


class _Svc:
    """Minimal stand-in exposing just the properties under test."""

    def __init__(self, fmt: str) -> None:
        self.msg_encoder = _FakeMsgEncoder(fmt)
        self._schema_registry_encoder = None
        self.built = 0

    # --- copies of the real property contracts -----------------------------
    @property
    def schema_registry_enabled(self) -> bool:
        return (
            self.msg_encoder.serialization_format
            == MessageEncodingType.SCHEMA_REGISTRY_AVRO
        )

    @property
    def schema_registry_encoder(self):
        if not self.schema_registry_enabled:
            raise RuntimeError('Schema registry is not enabled')
        self.built += 1
        return object()

    @property
    def schema_registry_encoder_or_none(self):
        if not self.schema_registry_enabled:
            return None
        return self.schema_registry_encoder


@pytest.mark.parametrize('fmt', ['msgpack', 'json'])
def test_or_none_returns_none_for_non_avro(fmt: str) -> None:
    svc = _Svc(fmt)
    assert svc.schema_registry_encoder_or_none is None
    assert svc.built == 0, 'must not attempt to build a registry client'


@pytest.mark.parametrize('fmt', ['msgpack', 'json'])
def test_strict_property_still_raises_for_non_avro(fmt: str) -> None:
    """Callers that genuinely require Avro must still get a loud failure."""
    with pytest.raises(RuntimeError, match='not enabled'):
        _ = _Svc(fmt).schema_registry_encoder


def test_or_none_returns_the_encoder_for_avro() -> None:
    svc = _Svc(MessageEncodingType.SCHEMA_REGISTRY_AVRO)
    assert svc.schema_registry_encoder_or_none is not None
    assert svc.built == 1


def test_real_services_use_the_non_raising_accessor() -> None:
    """Guard against a regression reintroducing the eager property."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for rel in (
        'messaging_faststream/src/messaging_faststream/faststream_aiokafka_impl.py',
        'messaging_kafka/src/messaging_kafka/aiokafka_messaging.py',
    ):
        path = root / rel
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if (
                'sr_encoder=self.schema_registry_encoder' in line
                and '_or_none' not in line
            ):
                offenders.append(f'{rel}:{i}')
    assert not offenders, (
        f'eager schema_registry_encoder passed through at: {offenders}'
    )
