"""
Saga executor (twin of ``@taas/resiliant`` ``saga/service.ts``) - runs a
definition step by step, checkpointing after every step and every compensation.

Durability contract:

* a crash between two checkpoints re-runs the step that was in flight when the
  saga is resumed - steps and compensations MUST be idempotent (use the
  idempotency guard or natural keys inside them);
* ``resume`` refuses an instance whose recorded step names are not in the
  definition (a renamed / removed step while instances were in flight);
* only ``Exception`` triggers compensation: a ``BaseException`` (task
  cancellation, ``KeyboardInterrupt``) propagates like a crash and leaves the
  instance RUNNING / COMPENSATING for ``resume``.

Signals merge data into the stored context (``jsonb ||``). A running executor
checkpoints its in-memory context and would overwrite keys it also holds, so
signal a saga that is parked (between ``run`` and ``resume``), under keys its
steps do not write.

Contracts (errors, statuses, protocols): ``foundation.resiliant.saga``.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.saga import (
    ISignalableSagaRepository,
    SagaAbortedError,
    SagaCompensationError,
    SagaConfig,
    SagaContext,
    SagaDefinition,
    SagaError,
    SagaInstance,
    SagaStatus,
    SagaStepRecord,
    SagaStepStatus,
    is_terminal_saga,
)

from resiliant.sql import describe_error

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


class SagaService:
    """Executes saga definitions and persists their progress (``ISagaService``)."""

    def __init__(
        self,
        repository: ISignalableSagaRepository,
        config: SagaConfig | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or SagaConfig()
        self._clock = clock or system_clock
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    @property
    def repository(self) -> ISignalableSagaRepository:
        return self._repository

    async def run(
        self,
        definition: SagaDefinition,
        context: SagaContext | None = None,
        *,
        saga_id: str | None = None,
        saga_key: str | None = None,
    ) -> SagaInstance:
        """Start a new instance and run it to the end (or compensate it).

        The first checkpoint raises :class:`SagaError` when ``(name, saga_key)``
        is already taken - one flow per business anchor.
        """
        now = self._clock()
        instance = SagaInstance(
            id=saga_id or str(uuid.uuid4()),
            name=definition.name,
            saga_key=saga_key,
            status=SagaStatus.RUNNING,
            context=copy.deepcopy(context) if context else {},
            steps=[
                SagaStepRecord(name=step.name, status=SagaStepStatus.PENDING, error=None)
                for step in definition.steps
            ],
            created_at=now,
            updated_at=now,
        )
        await self._checkpoint(instance)
        return await self._forward(definition, instance)

    async def resume(self, definition: SagaDefinition, saga_id: str) -> SagaInstance:
        """Continue an interrupted instance (RUNNING / COMPENSATING); a finished one is returned as is."""
        instance = await self._repository.get(saga_id)
        if instance is None:
            raise SagaError(f"saga {saga_id} not found")
        if instance.name != definition.name:
            raise SagaError(f'saga {saga_id} is a "{instance.name}", not a "{definition.name}"')
        if is_terminal_saga(instance):
            return instance
        known = {step.name for step in definition.steps}
        unknown = [s.name for s in instance.steps if s.name not in known]
        if unknown:
            raise SagaError(
                f"saga {saga_id} recorded steps the definition no longer has: {', '.join(unknown)}"
            )
        # Steps added to the definition after the instance started run in their definition order.
        recorded = {s.name: s for s in instance.steps}
        instance.steps = [
            recorded.get(step.name)
            or SagaStepRecord(name=step.name, status=SagaStepStatus.PENDING, error=None)
            for step in definition.steps
        ]
        self.logger.info(f"resuming saga {definition.name} {saga_id} ({instance.status})")
        if instance.status == SagaStatus.COMPENSATING:
            failed = next(
                (i for i, s in enumerate(instance.steps) if s.status == SagaStepStatus.FAILED),
                len(instance.steps),
            )
            return await self._compensate(definition, instance, failed, None)
        return await self._forward(definition, instance)

    async def signal(
        self, name: str, saga_key: str, patch: SagaContext
    ) -> SagaInstance | None:
        """Merge ``patch`` into the stored context of saga ``(name, saga_key)``.

        ``None`` when there is no such saga; a finished saga is returned unchanged.
        """
        instance = await self._repository.get_by_key(name, saga_key)
        if instance is None:
            return None
        if is_terminal_saga(instance):
            self.logger.warning(
                f"signal to finished saga {name}/{saga_key} ({instance.status}) ignored"
            )
            return instance
        await self._repository.merge_context(instance.id, patch, self._clock())
        return await self._repository.get(instance.id)

    # ------------------------------------------------------------------ #

    async def _forward(self, definition: SagaDefinition, instance: SagaInstance) -> SagaInstance:
        for index, step in enumerate(definition.steps):
            record = instance.steps[index] if index < len(instance.steps) else None
            if record is None or record.status == SagaStepStatus.COMPLETED:
                continue
            try:
                await step.action(instance.context)
            except Exception as error:
                record.status = SagaStepStatus.FAILED
                record.error = describe_error(error)
                instance.status = SagaStatus.COMPENSATING
                await self._checkpoint(instance)
                self.logger.warning(
                    f'saga {definition.name} {instance.id}: step "{step.name}" failed, compensating'
                )
                return await self._compensate(definition, instance, index, error)
            record.status = SagaStepStatus.COMPLETED
            record.error = None
            await self._checkpoint(instance)
        instance.status = SagaStatus.COMPLETED
        await self._checkpoint(instance)
        return instance

    async def _compensate(
        self,
        definition: SagaDefinition,
        instance: SagaInstance,
        failed_index: int,
        cause: BaseException | None,
    ) -> SagaInstance:
        """Undo the completed steps before ``failed_index``, newest first."""
        for index in range(failed_index - 1, -1, -1):
            step = definition.steps[index] if index < len(definition.steps) else None
            record = instance.steps[index] if index < len(instance.steps) else None
            if step is None or record is None or record.status != SagaStepStatus.COMPLETED:
                continue
            if step.compensation is not None:
                try:
                    await step.compensation(instance.context)
                except Exception as error:
                    record.error = f"compensation failed: {describe_error(error)}"
                    instance.status = SagaStatus.FAILED
                    await self._checkpoint(instance)
                    self.logger.error(
                        f'saga {definition.name} {instance.id}: compensation of "{step.name}" failed'
                    )
                    raise SagaCompensationError(instance.id, step.name, error) from error
            record.status = SagaStepStatus.COMPENSATED
            await self._checkpoint(instance)
        instance.status = SagaStatus.ABORTED
        await self._checkpoint(instance)
        failed_step = (
            definition.steps[failed_index].name
            if 0 <= failed_index < len(definition.steps)
            else "(unknown)"
        )
        if self._config.raise_on_abort:
            reason = cause if cause is not None else SagaError("resumed compensation")
            raise SagaAbortedError(instance.id, failed_step, reason) from reason
        return instance

    async def _checkpoint(self, instance: SagaInstance) -> None:
        instance.updated_at = self._clock()
        await self._repository.save(instance)


__all__ = ["Clock", "SagaService", "system_clock"]
