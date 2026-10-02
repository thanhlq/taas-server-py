"""
Entry point for building the saga service and its state store.

    build_saga_service()                    # Postgres store on the main database
    build_saga_service(SagaConfig(raise_on_abort=False), session_factory=maker)
    SagaFactory(MemorySagaRepository()).create_service()   # unit tests
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from foundation.resiliant.saga import ISignalableSagaRepository, SagaConfig

from .saga_repository import PgSagaRepository
from .saga_service import Clock, SagaService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def build_saga_repository(
    session_factory: Callable[[], AsyncSession] | None = None,
) -> PgSagaRepository:
    """Postgres store; without ``session_factory`` the main database is resolved on first use."""
    return PgSagaRepository(session_factory=session_factory)


def build_saga_service(
    config: SagaConfig | None = None,
    session_factory: Callable[[], AsyncSession] | None = None,
    *,
    repository: ISignalableSagaRepository | None = None,
) -> SagaService:
    """Durable saga service (``repository`` overrides the Postgres store)."""
    return SagaService(repository or build_saga_repository(session_factory), config)


class SagaFactory:
    """Builds :class:`SagaService` instances on one repository."""

    def __init__(
        self,
        repository: ISignalableSagaRepository,
        config: SagaConfig | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._clock = clock

    def create_service(self, config: SagaConfig | None = None) -> SagaService:
        return SagaService(self._repository, config or self._config, clock=self._clock)


__all__ = ['SagaFactory', 'build_saga_repository', 'build_saga_service']
