"""
Saga orchestration service — implementation (durable repository: ``resiliant.saga.SagaRepository``).

Definitions (errors, config, protocols) live in ``foundation.resiliant.saga``.
"""

from __future__ import annotations

import time
import uuid

from foundation.resiliant.saga import (
    ISagaRepository,
    SagaAbortedError,
    SagaCompensationError,
    SagaConfig,
    SagaContext,
    SagaDefinition,
    SagaInstance,
    SagaStatus,
    SagaStepRecord,
    SagaStepStatus,
)

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class SagaService:
    """Executes saga definitions and persists their progress."""

    def __init__(
        self,
        repository: ISagaRepository,
        config: SagaConfig | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or SagaConfig()

    async def run(
        self,
        definition: SagaDefinition,
        context: SagaContext | None = None,
        *,
        saga_id: str | None = None,
    ) -> SagaInstance:
        now = time.time()
        instance = SagaInstance(
            id=saga_id or str(uuid.uuid4()),
            name=definition.name,
            status=SagaStatus.RUNNING,
            context=dict(context or {}),
            steps=[SagaStepRecord(name=step.name) for step in definition.steps],
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(instance)

        for index, step in enumerate(definition.steps):
            try:
                await step.action(instance.context)
            except BaseException as exc:
                instance.steps[index].status = SagaStepStatus.FAILED
                instance.steps[index].error = repr(exc)
                instance.status = SagaStatus.COMPENSATING
                instance.updated_at = time.time()
                await self._repository.save(instance)
                await self._compensate(definition, instance, failed_index=index)
                if self._config.raise_on_abort and instance.status is SagaStatus.ABORTED:
                    raise SagaAbortedError(instance.id, step.name, exc) from exc
                return instance

            instance.steps[index].status = SagaStepStatus.COMPLETED
            instance.updated_at = time.time()
            await self._repository.save(instance)

        instance.status = SagaStatus.COMPLETED
        instance.updated_at = time.time()
        await self._repository.save(instance)
        return instance

    async def _compensate(
        self,
        definition: SagaDefinition,
        instance: SagaInstance,
        *,
        failed_index: int,
    ) -> None:
        for i in range(failed_index - 1, -1, -1):
            step = definition.steps[i]
            record = instance.steps[i]
            if record.status is not SagaStepStatus.COMPLETED or step.compensation is None:
                continue
            try:
                await step.compensation(instance.context)
            except BaseException as exc:
                record.error = f"compensation failed: {exc!r}"
                instance.status = SagaStatus.FAILED
                instance.updated_at = time.time()
                await self._repository.save(instance)
                raise SagaCompensationError(
                    f"Compensation for step {step.name!r} failed"
                ) from exc
            record.status = SagaStepStatus.COMPENSATED

        instance.status = SagaStatus.ABORTED
        instance.updated_at = time.time()
        await self._repository.save(instance)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class SagaFactory:
    """Builds `SagaService` instances."""

    def __init__(
        self,
        repository: ISagaRepository,
        config: SagaConfig | None = None,
    ) -> None:
        self._repository = repository
        self._config = config

    def create_service(self, config: SagaConfig | None = None) -> SagaService:
        return SagaService(
            repository=self._repository,
            config=config or self._config,
        )
