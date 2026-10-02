"""Dead-letter queue without a database: the contract shared with ``@taas/resiliant``
(statuses, transitions, config defaults / validation, ``DLQ_*`` settings), the handler
registry, and the retry step's settle logic on a fake repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from foundation.resiliant.dlq import (
    ARCHIVABLE_DLQ_STATUSES,
    DLQ_TRANSITIONS,
    RETRYABLE_DLQ_STATUSES,
    DeadLetterConfig,
    DeadLetterError,
    DLQStatus,
    can_transition_dlq,
)
from resiliant.dlq import (
    DLQHandlerRegistry,
    DLQRepository,
    DLQRetryProcessor,
    DLQService,
    DlqSettings,
    get_dlq_config,
    parse_handler_limits,
)

S = DLQStatus

# --------------------------------------------------------------------------- #
# Contract (must equal foundation/src/resiliant/dlq.ts and the table CHECK)
# --------------------------------------------------------------------------- #


def test_statuses_match_the_shared_table_check() -> None:
    assert {s.value for s in DLQStatus} == {
        'pending', 'approved', 'cancelled', 'processing', 'resolved', 'abandoned'
    }


def test_transitions_match_the_node_twin() -> None:
    assert dict(DLQ_TRANSITIONS) == {
        S.PENDING: (S.PROCESSING, S.APPROVED, S.CANCELLED, S.ABANDONED),
        S.APPROVED: (S.PROCESSING, S.CANCELLED),
        S.PROCESSING: (S.RESOLVED, S.PENDING, S.ABANDONED),
        S.ABANDONED: (S.APPROVED, S.CANCELLED),
        S.RESOLVED: (),
        S.CANCELLED: (),
    }
    assert ARCHIVABLE_DLQ_STATUSES == (S.RESOLVED, S.CANCELLED, S.ABANDONED)
    assert RETRYABLE_DLQ_STATUSES == (S.PENDING, S.APPROVED)
    assert can_transition_dlq('pending', 'approved')
    assert not can_transition_dlq(S.RESOLVED, S.PENDING)
    assert not can_transition_dlq('failed', 'pending')


def test_config_defaults_match_the_node_twin() -> None:
    c = DeadLetterConfig()
    assert (
        c.batch_size, c.page_size, c.max_retries, c.retry_backoff_multiplier,
        c.retry_max_interval_ms, c.claim_timeout_ms, c.archive_after_days, c.handler_max_retries,
    ) == (50, 100, 3, 2.0, 60_000, 300_000, 30, {})


@pytest.mark.parametrize(
    'overrides',
    [
        {'batch_size': 0},
        {'page_size': 0},
        {'max_retries': 0},
        {'archive_after_days': 0},
        {'retry_backoff_multiplier': 0.5},
        {'handler_max_retries': {'H': 0}},
    ],
)
def test_invalid_config_raises(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        DeadLetterConfig(**overrides)


# --------------------------------------------------------------------------- #
# DLQ_* settings
# --------------------------------------------------------------------------- #


def test_parse_handler_limits() -> None:
    assert parse_handler_limits('OrderHandler:5, Other:2') == {'OrderHandler': 5, 'Other': 2}
    assert parse_handler_limits('{"OrderHandler": 5}') == {'OrderHandler': 5}
    assert parse_handler_limits('') == {}
    for bad in ('OrderHandler', 'OrderHandler:0', ':3', 'OrderHandler:x', '[1]'):
        with pytest.raises(ValueError):
            parse_handler_limits(bad)


def test_settings_read_the_node_variable_names(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        'DLQ_BATCH_SIZE': '10',
        'DLQ_PAGE_SIZE': '20',
        'DLQ_MAX_RETRIES': '4',
        'DLQ_RETRY_BACKOFF_MULTIPLIER': '1.5',
        'DLQ_RETRY_MAX_INTERVAL_MS': '9000',
        'DLQ_CLAIM_TIMEOUT_MS': '1000',
        'DLQ_ARCHIVE_AFTER_DAYS': '7',
        'DLQ_HANDLER_MAX_RETRIES': 'OrderHandler:5,Other:2',
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert get_dlq_config() == DeadLetterConfig(
        batch_size=10,
        page_size=20,
        max_retries=4,
        retry_backoff_multiplier=1.5,
        retry_max_interval_ms=9000,
        claim_timeout_ms=1000,
        archive_after_days=7,
        handler_max_retries={'OrderHandler': 5, 'Other': 2},
    )


@pytest.mark.parametrize(
    ('key', 'value'),
    [
        ('DLQ_BATCH_SIZE', 'ten'),
        ('DLQ_BATCH_SIZE', '0'),
        ('DLQ_CLAIM_TIMEOUT_MS', '1.5'),
        ('DLQ_RETRY_BACKOFF_MULTIPLIER', 'fast'),
        ('DLQ_HANDLER_MAX_RETRIES', 'OrderHandler'),
    ],
)
def test_a_malformed_variable_raises(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        DlqSettings().get_config()


# --------------------------------------------------------------------------- #
# Service policy and registry
# --------------------------------------------------------------------------- #


def test_retry_budget_explicit_then_per_handler_then_default() -> None:
    service = DLQService(DeadLetterConfig(max_retries=3, handler_max_retries={'PayoutHandler': 5}))
    assert service.max_retries_for('PayoutHandler', 7) == 7
    assert service.max_retries_for('PayoutHandler') == 5
    assert service.max_retries_for('Other') == 3


async def test_illegal_transition_raises_before_touching_the_session() -> None:
    with pytest.raises(DeadLetterError, match='illegal'):
        await DLQRepository().transition(None, 1, [S.CANCELLED], S.APPROVED)  # type: ignore[arg-type]
    with pytest.raises(DeadLetterError, match='cannot patch'):
        await DLQRepository().transition(None, 1, [S.PENDING], S.APPROVED, status='x')  # type: ignore[arg-type]


@dataclass
class _Record:
    id: int
    handler_name: str
    event_id: str = 'e'
    retry_count: int = 0
    max_retries: int = 3


async def test_registry_routes_by_handler_name() -> None:
    seen: list[int] = []

    async def handler(record: Any) -> None:
        seen.append(record.id)

    registry = DLQHandlerRegistry().register('A', handler)
    await registry.replay(_Record(1, 'A'))  # type: ignore[arg-type]
    assert seen == [1]
    with pytest.raises(DeadLetterError, match='no dead-letter handler registered for "B"'):
        await registry.replay(_Record(2, 'B'))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Retry step on fakes
# --------------------------------------------------------------------------- #


class _FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        self.log.append('claim commit')


class _FakeSession:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.log.append('close')

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self.log)

    def expunge_all(self) -> None:
        self.log.append('expunge')

    async def commit(self) -> None:
        self.log.append('commit')


class _FakeRepository(DLQRepository):
    def __init__(self, records: list[_Record]) -> None:
        super().__init__()
        self.records = records
        self.transitions: list[tuple[int, S]] = []
        self.failures: list[tuple[int, str, float]] = []

    async def claim_due(self, session: Any, limit: int | None = None) -> list[Any]:
        return list(self.records)

    async def transition(self, session: Any, dlq_id: int, from_statuses: Any, to_status: S, **patch: Any) -> bool:
        self.transitions.append((dlq_id, to_status))
        return True

    async def record_failure(self, session: Any, record: Any, error: str, retry_in_ms: float) -> S:
        self.failures.append((record.id, error, retry_in_ms))
        return S.ABANDONED if record.retry_count + 1 >= record.max_retries else S.PENDING


async def test_retry_step_resolves_counts_failures_and_owns_its_transactions() -> None:
    records = [_Record(1, 'Ok'), _Record(2, 'Missing'), _Record(3, 'Missing', retry_count=2)]
    repository = _FakeRepository(records)  # type: ignore[arg-type]
    service = DLQService(DeadLetterConfig(retry_max_interval_ms=60_000), repository)
    log: list[str] = []

    async def ok(record: Any) -> None:
        log.append(f'replay {record.id}')

    processor = DLQRetryProcessor(
        service=service,
        session_factory=lambda: _FakeSession(log),  # type: ignore[arg-type,return-value]
        replayer=DLQHandlerRegistry().register('Ok', ok),
    )
    result = await processor.process_batch()
    assert (result.claimed, result.resolved, result.failed, result.abandoned) == (3, 1, 1, 1)
    assert repository.transitions == [(1, S.RESOLVED)]
    # backoff of attempt n = multiplier ** n seconds
    assert [(i, ms) for i, _, ms in repository.failures] == [(2, 2000.0), (3, 8000.0)]
    assert 'DeadLetterError' in repository.failures[0][1]
    # claim committed (rows detached) before any handler ran; one commit per settled record
    assert log[:4] == ['expunge', 'claim commit', 'close', 'replay 1']
    assert log.count('commit') == 3
