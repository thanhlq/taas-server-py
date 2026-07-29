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
