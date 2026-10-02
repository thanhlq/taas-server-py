"""Durable sagas on Postgres - mirrors taas-server-js ``tests/e2e/saga.test.ts``.

Checkpoints survive, compensation is recorded, a crashed process is resumed by
another one, business keys are unique, signals merge into the stored context
(``jsonb ||``), and the row shape is the one the Node twin reads and writes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from foundation.resiliant.saga import (
    SagaAbortedError,
    SagaContext,
    SagaError,
    SagaInstance,
    SagaStatus,
    SagaStep,
    SagaStepRecord,
    SagaStepStatus,
    define_saga,
)
from resiliant.saga import PgSagaRepository, SagaService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TABLE = "resiliant_saga_state"


@pytest.fixture
def repository(db_session: AsyncSession, db_engine) -> PgSagaRepository:
    # ``db_session`` truncates the resiliant tables after the test.
    return PgSagaRepository(async_sessionmaker(bind=db_engine, expire_on_commit=False))


@pytest.fixture
def log() -> list[str]:
    return []


@pytest.fixture
def withdrawal(log: list[str]):
    async def reserve(ctx: SagaContext) -> None:
        log.append("reserve")
        ctx["reservation"] = "res-1"

    async def release(_: SagaContext) -> None:
        log.append("release")

    async def broadcast(ctx: SagaContext) -> None:
        log.append("broadcast")
        if ctx.get("fail_broadcast"):
            raise RuntimeError("rpc rejected the transaction")
        ctx["tx_hash"] = "0xabc"

    async def notify(_: SagaContext) -> None:
        log.append("notify")

    return define_saga(
        "withdrawal",
        [
            SagaStep("reserve_funds", reserve, release),
            SagaStep("broadcast", broadcast),
            SagaStep("notify", notify),
        ],
    )


async def _raw_row(db_session: AsyncSession, saga_id: str) -> dict[str, Any]:
    result = await db_session.execute(
        text(
            f"select saga_id, name, saga_key, status, current_step, context, steps, last_error, "
            f"created_at, updated_at from {TABLE} where saga_id = :id"
        ),
        {"id": saga_id},
    )
    return dict(result.mappings().one())


async def test_persists_every_checkpoint_of_a_completed_flow(repository, withdrawal) -> None:
    saga = SagaService(repository)
    instance = await saga.run(withdrawal, {"amount": str(2**70)}, saga_key="wd-1")
    stored = await repository.get(instance.id)
    assert stored is not None
    assert stored.status == SagaStatus.COMPLETED and stored.saga_key == "wd-1"
    assert stored.context == {"amount": str(2**70), "reservation": "res-1", "tx_hash": "0xabc"}
    assert [s.status for s in stored.steps] == ["completed", "completed", "completed"]
    by_key = await repository.get_by_key("withdrawal", "wd-1")
    assert by_key is not None and by_key.id == instance.id
    stats = await repository.stats()
    assert stats["completed"] == 1 and stats["running"] == 0


async def test_records_the_failure_and_the_compensation(
    repository, withdrawal, log, db_session
) -> None:
    with pytest.raises(SagaAbortedError) as caught:
        await SagaService(repository).run(withdrawal, {"fail_broadcast": True})
    assert caught.value.failed_step == "broadcast"
    assert log == ["reserve", "broadcast", "release"]
    stored = await repository.get(caught.value.saga_id)
    assert stored is not None
    assert stored.status == SagaStatus.ABORTED
    assert [s.status for s in stored.steps] == ["compensated", "failed", "pending"]
    assert "rpc rejected" in (stored.steps[1].error or "")
    raw = await _raw_row(db_session, caught.value.saga_id)
    assert raw["current_step"] == "reserve_funds"  # first step not completed
    assert raw["last_error"] == "RuntimeError: rpc rejected the transaction"


async def test_another_process_resumes_a_flow_whose_process_died(repository, withdrawal, log) -> None:
    saves = 0

    class Dying:
        """Process 1 dies right after checkpointing "reserve_funds"."""

        async def save(self, instance: SagaInstance) -> None:
            nonlocal saves
            saves += 1
            await repository.save(instance)
            if saves == 2:
                raise RuntimeError("SIGKILL")

        get = repository.get
        get_by_key = repository.get_by_key
        stats = repository.stats
        merge_context = repository.merge_context

    with pytest.raises(RuntimeError, match="SIGKILL"):
        await SagaService(Dying()).run(withdrawal, {}, saga_id="wd-crash")  # type: ignore[arg-type]
    crashed = await repository.get("wd-crash")
    assert crashed is not None and crashed.status == SagaStatus.RUNNING
    assert [i.id for i in await repository.list_active(name="withdrawal")] == ["wd-crash"]

    # Process 2 picks it up: the reservation is not repeated.
    log.clear()
    resumed = await SagaService(repository).resume(withdrawal, "wd-crash")
    assert resumed.status == SagaStatus.COMPLETED
    assert log == ["broadcast", "notify"]
    assert await repository.list_active() == []


async def test_one_flow_per_business_key_and_signals_merge(repository) -> None:
    async def await_confirmations(ctx: SagaContext) -> None:
        if not ctx.get("confirmed"):
            raise RuntimeError("not yet")

    parked = define_saga("deposit_confirmation", [SagaStep("await_confirmations", await_confirmations)])
    saga = SagaService(repository)
    started = datetime.now(UTC)
    await repository.save(
        SagaInstance(
            id="dep-1",
            name="deposit_confirmation",
            saga_key="solana:mainnet:tx-9",
            status=SagaStatus.RUNNING,
            context={"amount": "5"},
            steps=[SagaStepRecord(name="await_confirmations")],
            created_at=started,
            updated_at=started,
        )
    )
    with pytest.raises(SagaError, match="already exists"):
        await saga.run(parked, {}, saga_key="solana:mainnet:tx-9")
    signalled = await saga.signal("deposit_confirmation", "solana:mainnet:tx-9", {"confirmed": True})
    assert signalled is not None
    assert signalled.context == {"amount": "5", "confirmed": True}
    assert signalled.updated_at > started
    assert (await saga.resume(parked, "dep-1")).status == SagaStatus.COMPLETED
    assert await saga.signal("deposit_confirmation", "unknown", {}) is None


async def test_null_keys_do_not_collide(repository, withdrawal) -> None:
    saga = SagaService(repository)
    await saga.run(withdrawal)
    await saga.run(withdrawal)
    assert (await repository.stats())["completed"] == 2


async def test_a_checkpoint_never_rewrites_another_definitions_row(repository, withdrawal) -> None:
    await SagaService(repository).run(withdrawal, saga_id="shared-id")
    now = datetime.now(UTC)
    with pytest.raises(SagaError, match="belongs to another definition"):
        await repository.save(
            SagaInstance(
                id="shared-id",
                name="other",
                status=SagaStatus.RUNNING,
                context={},
                steps=[SagaStepRecord(name="x")],
                created_at=now,
                updated_at=now,
            )
        )
    stored = await repository.get("shared-id")
    assert stored is not None and stored.name == "withdrawal"


async def test_row_has_the_node_shape(repository, withdrawal, db_session) -> None:
    instance = await SagaService(repository).run(withdrawal, {"amount": "7"}, saga_key="wd-shape")
    raw = await _raw_row(db_session, instance.id)
    assert raw["name"] == "withdrawal"
    assert raw["saga_key"] == "wd-shape"
    assert raw["status"] == "completed"
    assert raw["current_step"] is None and raw["last_error"] is None
    assert raw["context"] == {"amount": "7", "reservation": "res-1", "tx_hash": "0xabc"}
    assert raw["steps"] == [
        {"name": "reserve_funds", "status": "completed", "error": None},
        {"name": "broadcast", "status": "completed", "error": None},
        {"name": "notify", "status": "completed", "error": None},
    ]
    assert raw["created_at"].tzinfo is not None
    assert raw["updated_at"] >= raw["created_at"]


async def test_resumes_a_node_written_instance(repository, withdrawal, log, db_session) -> None:
    """A row as the Node ``PgSagaRepository`` writes it (crashed after "reserve_funds")."""
    steps = [
        {"name": "reserve_funds", "status": "completed", "error": None},
        {"name": "broadcast", "status": "pending", "error": None},
        {"name": "notify", "status": "pending", "error": None},
    ]
    await db_session.execute(
        text(
            f"insert into {TABLE} (saga_id, name, saga_key, status, current_step, context, steps, "
            f"last_error, created_at, updated_at) values (:id, 'withdrawal', 'node-1', 'running', "
            f"'broadcast', cast(:ctx as jsonb), cast(:steps as jsonb), null, now(), now())"
        ),
        {"id": "node-wd", "ctx": json.dumps({"reservation": "res-1"}), "steps": json.dumps(steps)},
    )
    await db_session.commit()

    resumed = await SagaService(repository).resume(withdrawal, "node-wd")
    assert resumed.status == SagaStatus.COMPLETED
    assert log == ["broadcast", "notify"]
    raw = await _raw_row(db_session, "node-wd")
    assert raw["saga_key"] == "node-1"
    assert [s["status"] for s in raw["steps"]] == ["completed"] * 3


async def test_builder_wires_a_durable_service(db_session, db_engine, withdrawal) -> None:
    from resiliant import ResiliantServiceBuilder

    service = ResiliantServiceBuilder.build_saga_service(
        session_factory=async_sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    instance = await service.run(withdrawal)
    assert instance.status == SagaStatus.COMPLETED
    assert (await service.repository.get(instance.id)) is not None
    assert SagaStepStatus.COMPLETED in {s.status for s in instance.steps}
