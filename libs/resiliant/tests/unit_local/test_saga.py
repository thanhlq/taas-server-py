"""SagaService on MemorySagaRepository - mirrors taas-server-js ``tests/unit/saga.test.ts``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from foundation.resiliant.saga import (
    SagaAbortedError,
    SagaCompensationError,
    SagaConfig,
    SagaContext,
    SagaDefinition,
    SagaError,
    SagaInstance,
    SagaStatus,
    SagaStep,
    SagaStepRecord,
    SagaStepStatus,
    define_saga,
)
from resiliant.saga import MemorySagaRepository, SagaFactory, SagaService


@pytest.fixture
def trace() -> list[str]:
    return []


@pytest.fixture
def step(trace: list[str]):
    def make(name: str, *, fail: bool = False, fail_undo: bool = False) -> SagaStep:
        async def action(ctx: SagaContext) -> None:
            trace.append(f"do:{name}")
            if fail:
                raise RuntimeError(f"{name} failed")
            ctx[name] = True

        async def compensation(_: SagaContext) -> None:
            trace.append(f"undo:{name}")
            if fail_undo:
                raise RuntimeError(f"undo {name} failed")

        return SagaStep(name, action, compensation)

    return make


def _stored(saga_id: str, name: str, steps: list[SagaStepRecord], **kw) -> SagaInstance:
    now = datetime.now(UTC)
    return SagaInstance(
        id=saga_id,
        name=name,
        saga_key=kw.get("saga_key"),
        status=kw.get("status", SagaStatus.RUNNING),
        context=kw.get("context", {}),
        steps=steps,
        created_at=now,
        updated_at=now,
    )


async def test_runs_every_step_checkpointing_the_context(step) -> None:
    repository = MemorySagaRepository()
    instance = await SagaService(repository).run(
        define_saga("deposit", [step("reserve"), step("credit")]), {"amount": "10"}
    )
    assert instance.status == SagaStatus.COMPLETED
    assert instance.context == {"amount": "10", "reserve": True, "credit": True}
    stored = await repository.get(instance.id)
    assert stored is not None
    assert [s.status for s in stored.steps] == ["completed", "completed"]


async def test_run_does_not_mutate_the_callers_context(step) -> None:
    context = {"amount": "10"}
    await SagaService(MemorySagaRepository()).run(define_saga("d", [step("a")]), context)
    assert context == {"amount": "10"}


async def test_compensates_in_reverse_order_and_raises_aborted(step, trace) -> None:
    repository = MemorySagaRepository()
    definition = define_saga("withdraw", [step("a"), step("b"), step("c", fail=True)])
    with pytest.raises(SagaAbortedError) as caught:
        await SagaService(repository).run(definition)
    assert caught.value.failed_step == "c"
    assert trace == ["do:a", "do:b", "do:c", "undo:b", "undo:a"]
    stored = await repository.get(caught.value.saga_id)
    assert stored is not None
    assert stored.status == SagaStatus.ABORTED
    assert [s.status for s in stored.steps] == ["compensated", "compensated", "failed"]
    assert stored.steps[2].error == "RuntimeError: c failed"


async def test_a_step_without_compensation_is_still_marked_compensated() -> None:
    async def ok(_: SagaContext) -> None:
        pass

    async def boom(_: SagaContext) -> None:
        raise RuntimeError("x")

    service = SagaService(MemorySagaRepository(), SagaConfig(raise_on_abort=False))
    instance = await service.run(define_saga("x", [SagaStep("a", ok), SagaStep("b", boom)]))
    assert [s.status for s in instance.steps] == ["compensated", "failed"]


async def test_returns_the_aborted_instance_when_raise_on_abort_is_off(step) -> None:
    service = SagaService(MemorySagaRepository(), SagaConfig(raise_on_abort=False))
    instance = await service.run(define_saga("x", [step("a"), step("b", fail=True)]))
    assert instance.status == SagaStatus.ABORTED


async def test_a_failing_compensation_leaves_the_saga_failed(step) -> None:
    repository = MemorySagaRepository()
    with pytest.raises(SagaCompensationError) as caught:
        await SagaService(repository).run(
            define_saga("x", [step("a", fail_undo=True), step("b", fail=True)])
        )
    assert caught.value.step == "a"
    stored = await repository.get(caught.value.saga_id)
    assert stored is not None
    assert stored.status == SagaStatus.FAILED
    assert stored.steps[0].error is not None
    assert stored.steps[0].error.startswith("compensation failed")


async def test_resumes_from_the_first_incomplete_step(step, trace) -> None:
    repository = MemorySagaRepository()
    await repository.save(
        _stored(
            "crashed-1",
            "deposit",
            [
                SagaStepRecord(name="reserve", status=SagaStepStatus.COMPLETED),
                SagaStepRecord(name="credit", status=SagaStepStatus.PENDING),
            ],
            context={"reserve": True},
        )
    )
    definition = define_saga("deposit", [step("reserve"), step("credit"), step("notify")])
    resumed = await SagaService(repository).resume(definition, "crashed-1")
    assert resumed.status == SagaStatus.COMPLETED
    # The completed step is not repeated; a step added since then runs too.
    assert trace == ["do:credit", "do:notify"]


async def test_resumes_an_interrupted_compensation(step, trace) -> None:
    repository = MemorySagaRepository()
    await repository.save(
        _stored(
            "comp-1",
            "withdraw",
            [
                SagaStepRecord(name="a", status=SagaStepStatus.COMPLETED),
                SagaStepRecord(name="b", status=SagaStepStatus.COMPENSATED),
                SagaStepRecord(name="c", status=SagaStepStatus.FAILED, error="boom"),
            ],
            status=SagaStatus.COMPENSATING,
        )
    )
    definition = define_saga("withdraw", [step("a"), step("b"), step("c")])
    with pytest.raises(SagaAbortedError, match="resumed compensation"):
        await SagaService(repository).resume(definition, "comp-1")
    assert trace == ["undo:a"]
    stored = await repository.get("comp-1")
    assert stored is not None
    assert stored.status == SagaStatus.ABORTED


async def test_resume_returns_a_finished_instance_unchanged(step, trace) -> None:
    repository = MemorySagaRepository()
    await repository.save(
        _stored(
            "done-1",
            "deposit",
            [SagaStepRecord(name="a", status=SagaStepStatus.COMPLETED)],
            status=SagaStatus.COMPLETED,
        )
    )
    resumed = await SagaService(repository).resume(define_saga("deposit", [step("a")]), "done-1")
    assert resumed.status == SagaStatus.COMPLETED
    assert trace == []


async def test_resume_refusals(step) -> None:
    repository = MemorySagaRepository()
    await repository.save(
        _stored("old-1", "deposit", [SagaStepRecord(name="renamed-step")])
    )
    service = SagaService(repository)
    with pytest.raises(SagaError, match="no longer has"):
        await service.resume(define_saga("deposit", [step("credit")]), "old-1")
    with pytest.raises(SagaError, match="not found"):
        await service.resume(define_saga("deposit", [step("credit")]), "missing")
    with pytest.raises(SagaError, match='is a "deposit", not a "other"'):
        await service.resume(define_saga("other", [step("credit")]), "old-1")


async def test_signal_by_key_and_one_flow_per_key(step) -> None:
    repository = MemorySagaRepository()
    saga = SagaService(repository, SagaConfig(raise_on_abort=False))
    first = await saga.run(define_saga("confirm", [step("a")]), {}, saga_key="tx-1")
    assert first.status == SagaStatus.COMPLETED
    with pytest.raises(SagaError, match="already exists"):
        await saga.run(define_saga("confirm", [step("a"), step("wait", fail=True)]), saga_key="tx-1")
    # A finished saga is not signalled.
    finished = await saga.signal("confirm", "tx-1", {"confirmed": True})
    assert finished is not None and "confirmed" not in finished.context
    assert await saga.signal("confirm", "unknown", {}) is None
    # The same key under another saga name is another flow.
    other = await saga.run(define_saga("other", [step("a")]), saga_key="tx-1")
    assert other.status == SagaStatus.COMPLETED


async def test_signal_merges_into_a_parked_saga(step) -> None:
    repository = MemorySagaRepository()
    await repository.save(
        _stored(
            "dep-1",
            "deposit_confirmation",
            [SagaStepRecord(name="await")],
            saga_key="k-1",
            context={"amount": "5"},
        )
    )
    signalled = await SagaService(repository).signal("deposit_confirmation", "k-1", {"confirmed": True})
    assert signalled is not None
    assert signalled.context == {"amount": "5", "confirmed": True}


async def test_stats_lists_every_status(step) -> None:
    repository = MemorySagaRepository()
    await SagaService(repository).run(define_saga("d", [step("a")]))
    assert await repository.stats() == {
        "running": 0,
        "completed": 1,
        "compensating": 0,
        "aborted": 0,
        "failed": 0,
    }


async def test_cancellation_is_a_crash_not_a_failure() -> None:
    import asyncio

    async def cancelled(_: SagaContext) -> None:
        raise asyncio.CancelledError

    repository = MemorySagaRepository()
    with pytest.raises(asyncio.CancelledError):
        await SagaService(repository).run(define_saga("d", [SagaStep("a", cancelled)]), saga_id="c-1")
    stored = await repository.get("c-1")
    assert stored is not None
    assert stored.status == SagaStatus.RUNNING  # resumable


async def test_factory_builds_service() -> None:
    assert isinstance(SagaFactory(MemorySagaRepository()).create_service(), SagaService)


def test_validates_definitions(step) -> None:
    with pytest.raises(SagaError):
        define_saga("empty", [])
    with pytest.raises(SagaError):
        define_saga("dup", [step("a"), step("a")])
    with pytest.raises(SagaError):
        SagaDefinition("", [step("a")])


async def test_checkpoints_after_every_step_and_every_compensation(step) -> None:
    saved: list[tuple[str, list[str]]] = []

    class Recording(MemorySagaRepository):
        async def save(self, instance: SagaInstance) -> None:
            saved.append((str(instance.status), [str(s.status) for s in instance.steps]))
            await super().save(instance)

    service = SagaService(Recording(), SagaConfig(raise_on_abort=False))
    await service.run(define_saga("x", [step("a"), step("b"), step("c", fail=True)]))
    assert saved == [
        ("running", ["pending", "pending", "pending"]),
        ("running", ["completed", "pending", "pending"]),
        ("running", ["completed", "completed", "pending"]),
        ("compensating", ["completed", "completed", "failed"]),
        ("compensating", ["completed", "compensated", "failed"]),
        ("compensating", ["compensated", "compensated", "failed"]),
        ("aborted", ["compensated", "compensated", "failed"]),
    ]
