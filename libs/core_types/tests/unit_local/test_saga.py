"""Tests for `core_types.resilience.saga`."""

from __future__ import annotations

import pytest

from core_types.resilience.saga import (
    ISagaRepository,
    SagaAbortedError,
    SagaCompensationError,
    SagaConfig,
    SagaContext,
    SagaDefinition,
    SagaFactory,
    SagaInstance,
    SagaService,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
)


class InMemorySagaRepository(ISagaRepository):
    def __init__(self) -> None:
        self._store: dict[str, SagaInstance] = {}

    async def save(self, instance: SagaInstance) -> None:
        self._store[instance.id] = instance

    async def get(self, saga_id: str) -> SagaInstance | None:
        return self._store.get(saga_id)


@pytest.fixture
def repo() -> InMemorySagaRepository:
    return InMemorySagaRepository()


async def test_runs_all_steps_to_completion(repo: InMemorySagaRepository) -> None:
    order: list[str] = []

    async def s1(ctx: SagaContext) -> None:
        order.append("s1")
        ctx["s1"] = True

    async def s2(ctx: SagaContext) -> None:
        order.append("s2")

    service = SagaService(repo)
    instance = await service.run(
        SagaDefinition("demo", [SagaStep("s1", s1), SagaStep("s2", s2)])
    )

    assert order == ["s1", "s2"]
    assert instance.status is SagaStatus.COMPLETED
    assert all(s.status is SagaStepStatus.COMPLETED for s in instance.steps)


async def test_compensates_in_reverse_on_failure(
    repo: InMemorySagaRepository,
) -> None:
    order: list[str] = []

    async def s1(_: SagaContext) -> None:
        order.append("s1")

    async def s1_comp(_: SagaContext) -> None:
        order.append("s1.comp")

    async def s2(_: SagaContext) -> None:
        order.append("s2")

    async def s2_comp(_: SagaContext) -> None:
        order.append("s2.comp")

    async def s3(_: SagaContext) -> None:
        raise RuntimeError("boom")

    service = SagaService(repo, SagaConfig(raise_on_abort=False))
    instance = await service.run(
        SagaDefinition(
            "demo",
            [
                SagaStep("s1", s1, s1_comp),
                SagaStep("s2", s2, s2_comp),
                SagaStep("s3", s3),
            ],
        )
    )

    assert order == ["s1", "s2", "s2.comp", "s1.comp"]
    assert instance.status is SagaStatus.ABORTED
    assert instance.steps[0].status is SagaStepStatus.COMPENSATED
    assert instance.steps[1].status is SagaStepStatus.COMPENSATED
    assert instance.steps[2].status is SagaStepStatus.FAILED


async def test_raises_aborted_when_configured(repo: InMemorySagaRepository) -> None:
    async def boom(_: SagaContext) -> None:
        raise RuntimeError("x")

    service = SagaService(repo)
    with pytest.raises(SagaAbortedError):
        await service.run(SagaDefinition("d", [SagaStep("s1", boom)]))


async def test_compensation_failure_raises(repo: InMemorySagaRepository) -> None:
    async def s1(_: SagaContext) -> None:
        pass

    async def bad_comp(_: SagaContext) -> None:
        raise RuntimeError("comp died")

    async def s2(_: SagaContext) -> None:
        raise RuntimeError("trigger")

    service = SagaService(repo)
    with pytest.raises(SagaCompensationError):
        await service.run(
            SagaDefinition(
                "d",
                [SagaStep("s1", s1, bad_comp), SagaStep("s2", s2)],
            )
        )

    stored = await repo.get(list(repo._store.keys())[0])
    assert stored is not None
    assert stored.status is SagaStatus.FAILED


async def test_factory_builds_service(repo: InMemorySagaRepository) -> None:
    assert isinstance(SagaFactory(repo).create_service(), SagaService)


def test_empty_definition_rejected() -> None:
    with pytest.raises(ValueError):
        SagaDefinition("d", [])
