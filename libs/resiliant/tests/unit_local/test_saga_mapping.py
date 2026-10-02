"""Row mapping of the saga store: the ``resiliant_saga_state`` shape shared with taas-server-js.

A row written by the Node ``PgSagaRepository`` must load here (and vice versa):
``steps`` items are ``{name, status, error}``, ``saga_key`` is its own column,
``current_step`` / ``last_error`` are derived from the step records.
"""

from __future__ import annotations

from datetime import UTC, datetime

from foundation.resiliant.saga import SagaInstance, SagaStatus, SagaStepRecord, SagaStepStatus
from resiliant.models import SagaStateTable
from resiliant.saga.saga_repository import (
    current_step,
    instance_to_values,
    last_error,
    row_to_instance,
    to_json,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _make_instance() -> SagaInstance:
    return SagaInstance(
        id="saga-123",
        name="deposit",
        saga_key="eth:mainnet:0xabc",
        status=SagaStatus.RUNNING,
        context={"amount": "10"},
        steps=[
            SagaStepRecord(name="persist", status=SagaStepStatus.COMPLETED),
            SagaStepRecord(name="credit", status=SagaStepStatus.FAILED, error="Error: rpc down"),
            SagaStepRecord(name="notify"),
        ],
        created_at=T0,
        updated_at=T0,
    )


def test_current_step_is_first_incomplete() -> None:
    assert current_step(_make_instance()) == "credit"


def test_current_step_none_when_all_complete() -> None:
    inst = _make_instance()
    for record in inst.steps:
        record.status = SagaStepStatus.COMPLETED
    assert current_step(inst) is None


def test_last_error_is_the_newest_and_clipped() -> None:
    inst = _make_instance()
    assert last_error(inst) == "Error: rpc down"
    inst.steps[2].error = "x" * 1500
    clipped = last_error(inst)
    assert clipped is not None and len(clipped) <= 1001 and clipped.endswith("…")


def test_values_have_the_node_shape() -> None:
    values = instance_to_values(_make_instance())
    assert values["saga_id"] == "saga-123"
    assert values["saga_key"] == "eth:mainnet:0xabc"
    assert values["current_step"] == "credit"
    assert values["last_error"] == "Error: rpc down"
    assert values["steps"] == [
        {"name": "persist", "status": "completed", "error": None},
        {"name": "credit", "status": "failed", "error": "Error: rpc down"},
        {"name": "notify", "status": "pending", "error": None},
    ]
    assert values["created_at"] == T0 and values["updated_at"] == T0


def test_a_node_written_row_loads() -> None:
    row = SagaStateTable(
        saga_id="wd-1",
        name="withdrawal",
        saga_key=None,
        status="compensating",
        current_step="broadcast",
        context={"reservation": "res-1"},
        steps=[
            {"name": "reserve_funds", "status": "completed", "error": None},
            {"name": "broadcast", "status": "failed", "error": "Error: rpc rejected"},
            {"name": "notify", "status": "pending"},  # error key absent -> None
        ],
        last_error="Error: rpc rejected",
        created_at=T0,
        updated_at=T0,
    )
    restored = row_to_instance(row)
    assert restored.id == "wd-1"
    assert restored.saga_key is None
    assert restored.status == SagaStatus.COMPENSATING
    assert [(s.name, s.status, s.error) for s in restored.steps] == [
        ("reserve_funds", SagaStepStatus.COMPLETED, None),
        ("broadcast", SagaStepStatus.FAILED, "Error: rpc rejected"),
        ("notify", SagaStepStatus.PENDING, None),
    ]


def test_round_trip() -> None:
    original = _make_instance()
    restored = row_to_instance(SagaStateTable(**instance_to_values(original)))
    assert restored == original


def test_context_is_json_safe() -> None:
    assert to_json({"raw": b"\x01\xff", "at": T0, "n": 2**70, "nested": [b"\x00"]}) == {
        "raw": "01ff",
        "at": "2026-01-01T00:00:00Z",
        "n": 2**70,
        "nested": ["00"],
    }
