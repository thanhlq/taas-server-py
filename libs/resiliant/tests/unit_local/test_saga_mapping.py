"""Round-trip + durability tests for the saga repository mapping.

Uses a *serializing* fake repository — save/get pass through the real
``_instance_to_values`` / ``_row_to_instance`` mapping via a detached ORM object
(no database) — so it verifies the persistence contract and the durable-workflow
semantics of ``SagaService`` together.
"""

from __future__ import annotations

from db.models.resiliant import SagaStateTable
from foundation.resiliant.saga import (
    SagaContext,
    SagaDefinition,
    SagaInstance,
    SagaService,
    SagaStatus,
    SagaStep,
    SagaStepRecord,
    SagaStepStatus,
)
from resiliant.saga.saga_repository import (
    _current_step,
    _instance_to_values,
    _row_to_instance,
)


def _make_instance() -> SagaInstance:
    return SagaInstance(
        id='saga-123',
        name='deposit',
        status=SagaStatus.RUNNING,
        context={'saga_key': 'eth:mainnet:0xabc', 'amount': 10},
        steps=[
            SagaStepRecord(name='persist', status=SagaStepStatus.COMPLETED),
            SagaStepRecord(name='credit', status=SagaStepStatus.PENDING),
        ],
        created_at=1000.0,
        updated_at=1001.0,
    )


def test_current_step_is_first_incomplete() -> None:
    assert _current_step(_make_instance()) == 'credit'


def test_current_step_none_when_all_complete() -> None:
    inst = _make_instance()
    for record in inst.steps:
        record.status = SagaStepStatus.COMPLETED
    assert _current_step(inst) is None


def test_instance_round_trips_through_the_orm_mapping() -> None:
    original = _make_instance()
    values = _instance_to_values(original)

    # saga_key is projected out of the context for indexed signals/queries.
    assert values['saga_key'] == 'eth:mainnet:0xabc'
    assert values['current_step'] == 'credit'

    row = SagaStateTable(**values)
    restored = _row_to_instance(row)

    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.status is SagaStatus.RUNNING
    assert restored.context == original.context
    assert [(s.name, s.status) for s in restored.steps] == [
        ('persist', SagaStepStatus.COMPLETED),
        ('credit', SagaStepStatus.PENDING),
    ]
    assert restored.created_at == 1000.0


class SerializingFakeRepository:
    """Fake ISagaRepository that persists via the real ORM mapping (no DB)."""

    def __init__(self) -> None:
        self.rows: dict[str, SagaStateTable] = {}
        self.save_calls = 0

    async def save(self, instance: SagaInstance) -> None:
        self.save_calls += 1
        self.rows[instance.id] = SagaStateTable(**_instance_to_values(instance))

    async def get(self, saga_id: str) -> SagaInstance | None:
        row = self.rows.get(saga_id)
        return _row_to_instance(row) if row is not None else None


async def test_saga_service_persists_durable_state() -> None:
    repo = SerializingFakeRepository()

    async def s1(ctx: SagaContext) -> None:
        ctx['s1'] = True

    async def s2(ctx: SagaContext) -> None:
        ctx['s2'] = True

    service = SagaService(repo)  # type: ignore[arg-type]
    instance = await service.run(
        SagaDefinition('deposit', [SagaStep('s1', s1), SagaStep('s2', s2)]),
        context={'saga_key': 'k-1'},
        saga_id='saga-abc',
    )

    assert instance.status is SagaStatus.COMPLETED
    # State was checkpointed after every step (start + 2 steps + final).
    assert repo.save_calls >= 3

    reloaded = await repo.get('saga-abc')
    assert reloaded is not None
    assert reloaded.status is SagaStatus.COMPLETED
    assert reloaded.context['s1'] is True and reloaded.context['s2'] is True
    assert _current_step(reloaded) is None
