"""
Saga-state database model (durable workflow state).

Backs :class:`foundation.resiliant.saga.SagaService` via
:class:`resiliant.saga.SagaRepository`. Persisting a :class:`SagaInstance` after
every step is what makes a saga *durable*: on a crash the state (which steps
completed, the accumulated context) survives, so the flow can be resumed,
queried, or signalled from outside — the Temporal "durable workflow" equivalent.

The ``saga_key`` column is the business anchor (e.g. ``eth:mainnet:0xabc``) used
for *signals* and *queries*: an external event looks the saga up by
``(name, saga_key)`` and merges data into ``context``; a read API selects the
same row to answer "what is the state of this flow?".
"""

from typing import Any, Dict

from advanced_alchemy.base import UUIDv7AuditBase
from foundation.resiliant.saga import SagaStatus
from sqlalchemy import (
    JSON,
    Column,
    Enum,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.models.config import RESILIANT_TABLE_PREFIX


class SagaStateTable(UUIDv7AuditBase):
    """Persisted state of a running or finished saga.

    Indexes:
        - uq_saga_id: the saga's own identity (used by ``get(saga_id)``).
        - uq_saga_name_key: business anchor for signals/queries.
        - idx_saga_status: visibility ("all IN_PROGRESS deposit sagas").
    """

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}saga_state'

    saga_id = Column(String(64), nullable=False, unique=True, index=True)
    """The :class:`SagaInstance` id (distinct from the surrogate row ``id``)."""

    name = Column(String(255), nullable=False, index=True)
    """The saga definition name, e.g. ``'deposit'``."""

    saga_key = Column(String(255), nullable=True, index=True)
    """Business anchor for signals/queries (derived from ``context['saga_key']``)."""

    status = Column(
        Enum(SagaStatus), nullable=False, default=SagaStatus.RUNNING, index=True
    )

    current_step = Column(String(255), nullable=True)
    """Name of the first non-completed step — the human-readable resume pointer."""

    context = Column(JSON, nullable=False, default=dict)
    """Accumulated, mutable saga context (JSON)."""

    steps = Column(JSON, nullable=False, default=list)
    """Per-step records: ``[{"name", "status", "error"}, ...]``."""

    last_error = Column(Text, nullable=True)

    # The saga's own logical clock (epoch seconds), kept alongside the audit
    # columns so the in-memory ``SagaInstance`` round-trips losslessly.
    saga_created_at: Mapped[float] = mapped_column(Float, nullable=False)
    saga_updated_at: Mapped[float] = mapped_column(Float, nullable=False)

    def as_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-safe dictionary."""
        return {
            'id': self.id,
            'saga_id': self.saga_id,
            'name': self.name,
            'saga_key': self.saga_key,
            'status': self.status.value if self.status else None,
            'current_step': self.current_step,
            'context': self.context,
            'steps': self.steps,
            'last_error': self.last_error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f'<SagaState(saga_id={self.saga_id}, name={self.name}, '
            f'status={self.status}, current_step={self.current_step})>'
        )


# Business anchor for signals/queries — one live saga per (name, key).
UniqueConstraint(
    SagaStateTable.name,
    SagaStateTable.saga_key,
    name='uq_saga_name_key',
)
# Visibility: list sagas by status.
Index(
    'idx_saga_status',
    SagaStateTable.status,
    SagaStateTable.name,
)
