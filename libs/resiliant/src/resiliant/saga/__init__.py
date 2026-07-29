"""Durable saga state (database-backed ``ISagaRepository`` implementation).

Pairs :class:`foundation.resiliant.saga.SagaService` (the executor) with a
Postgres-backed :class:`SagaRepository` (the durable store), giving Temporal-
style durable workflows: crash-resume, signals, queries, and compensation.
"""

from .saga_repository import SagaRepository

__all__ = ['SagaRepository']
