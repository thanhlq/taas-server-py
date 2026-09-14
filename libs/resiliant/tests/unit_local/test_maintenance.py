"""Tests for the outbox maintenance scheduling helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from resiliant.maintenances import resiliant_maintenance as m
from resiliant.outbox.partition_maintenance import OutboxMaintenanceResult


def test_default_cron_is_daily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('RESILIANT_MAINTENANCE_TEST_MODE', raising=False)
    monkeypatch.delenv('RESILIANT_MAINTENANCE_CRON', raising=False)
    assert m.maintenance_cron() == m.DEFAULT_MAINTENANCE_CRON == '0 2 * * *'


def test_test_mode_uses_five_minute_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('RESILIANT_MAINTENANCE_TEST_MODE', 'true')
    assert m.maintenance_cron() == '*/5 * * * *'


def test_cron_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('RESILIANT_MAINTENANCE_TEST_MODE', raising=False)
    monkeypatch.setenv('RESILIANT_MAINTENANCE_CRON', '0 */6 * * *')
    assert m.maintenance_cron() == '0 */6 * * *'


def test_register_wires_callback_under_job_name() -> None:
    registered: dict[str, Any] = {}

    class FakePoller:
        def register(self, job_name: str, callback: Any) -> None:
            registered[job_name] = callback

    m.register_maintenance_callbacks(FakePoller())  # type: ignore[arg-type]
    assert m.OUTBOX_MAINTENANCE_JOB in registered
    assert registered[m.OUTBOX_MAINTENANCE_JOB] is m.run_outbox_maintenance


async def test_run_outbox_maintenance_invokes_maintainer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, int]] = []

    class FakeMaintainer:
        async def maintain(self, *, lookahead_weeks: int, retention_weeks: int):
            calls.append(
                {'lookahead_weeks': lookahead_weeks, 'retention_weeks': retention_weeks}
            )
            return OutboxMaintenanceResult(created=['p_2026w05'], dropped=[])

    monkeypatch.setattr(m, 'get_outbox_partition_maintainer', lambda: FakeMaintainer())

    job = SimpleNamespace(payload={'lookahead_weeks': 6, 'retention_weeks': 20})
    await m.run_outbox_maintenance(job)  # type: ignore[arg-type]

    assert calls == [{'lookahead_weeks': 6, 'retention_weeks': 20}]


async def test_run_outbox_maintenance_uses_defaults_when_payload_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, int]] = []

    class FakeMaintainer:
        async def maintain(self, *, lookahead_weeks: int, retention_weeks: int):
            calls.append(
                {'lookahead_weeks': lookahead_weeks, 'retention_weeks': retention_weeks}
            )
            return OutboxMaintenanceResult()

    monkeypatch.setattr(m, 'get_outbox_partition_maintainer', lambda: FakeMaintainer())

    await m.run_outbox_maintenance(SimpleNamespace(payload=None))  # type: ignore[arg-type]

    assert calls == [
        {
            'lookahead_weeks': m.DEFAULT_LOOKAHEAD_WEEKS,
            'retention_weeks': m.DEFAULT_RETENTION_WEEKS,
        }
    ]


# --------------------------------------------------------------------------- #
# Partition-function availability (plain, unpartitioned outbox table)
# --------------------------------------------------------------------------- #

from contextlib import asynccontextmanager

from resiliant.outbox import partition_maintenance as pm


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value

    def __iter__(self):
        return iter(self._value or [])


class _FakeConn:
    """Records executed SQL; the first statement is the to_regproc probe."""

    def __init__(self, available: bool) -> None:
        self.available = available
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: dict | None = None) -> _FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        if 'to_regproc' in sql:
            return _FakeResult(self.available)
        return _FakeResult([SimpleNamespace(partition_name='p_2026w05')])


class _FakeDb:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connect(self):
        yield self.conn


@pytest.mark.parametrize(
    ('prefix', 'expected'),
    [
        ('taas', 'taas_create_message_outbox_partitions'),
        ('taas_', 'taas_create_message_outbox_partitions'),
        ('taas.', 'taas.create_message_outbox_partitions'),
        ('', 'create_message_outbox_partitions'),
    ],
)
def test_qualified_name_uses_table_prefix_convention(prefix: str, expected: str) -> None:
    maintainer = pm.OutboxPartitionMaintainer(prefix=prefix, db_manager=_FakeDb(_FakeConn(True)))
    assert maintainer.qualified_name(pm.CREATE_PARTITIONS_FN) == expected


async def test_maintain_skips_when_partition_functions_missing() -> None:
    conn = _FakeConn(available=False)
    maintainer = pm.OutboxPartitionMaintainer(prefix='taas', db_manager=_FakeDb(conn))

    result = await maintainer.maintain(lookahead_weeks=4, retention_weeks=12)

    assert result == pm.OutboxMaintenanceResult()
    assert len(conn.statements) == 1 and 'to_regproc' in conn.statements[0]


async def test_maintain_calls_both_functions_when_available() -> None:
    conn = _FakeConn(available=True)
    maintainer = pm.OutboxPartitionMaintainer(prefix='taas', db_manager=_FakeDb(conn))

    result = await maintainer.maintain(lookahead_weeks=4, retention_weeks=12)

    assert result.created == ['p_2026w05'] and result.dropped == ['p_2026w05']
    assert any('taas_create_message_outbox_partitions(' in s for s in conn.statements)
    assert any('taas_drop_old_message_outbox_partitions(' in s for s in conn.statements)


async def test_is_available_probes_with_to_regproc() -> None:
    conn = _FakeConn(available=True)
    maintainer = pm.OutboxPartitionMaintainer(prefix='taas', db_manager=_FakeDb(conn))
    assert await maintainer.is_available() is True
    conn.available = False
    assert await maintainer.is_available() is False


async def test_define_maintenance_jobs_skips_when_functions_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('RESILIANT_MAINTENANCE_ENABLED', raising=False)

    class FakeMaintainer:
        async def is_available(self) -> bool:
            return False

    monkeypatch.setattr(m, 'get_outbox_partition_maintainer', lambda: FakeMaintainer())

    def _boom():
        raise AssertionError('schedule service must not be touched when functions are missing')

    monkeypatch.setattr(m, 'ResiliantServiceFactory', _boom)

    await m.define_maintenance_jobs()  # returns without scheduling
