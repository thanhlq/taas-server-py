"""Sagas: the orchestration service plus the durable (Postgres) state store.

:class:`SagaService` (executor, contract ``foundation.resiliant.saga.ISagaService``)
paired with :class:`SagaRepository` gives Temporal-style durable workflows:
crash-resume, signals, queries, and compensation.
"""

from .saga_repository import SagaRepository
from .saga_service import SagaFactory, SagaService

__all__ = ['SagaFactory', 'SagaRepository', 'SagaService']
