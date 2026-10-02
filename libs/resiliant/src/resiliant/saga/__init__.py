"""Durable sagas (twin of ``@taas/resiliant/saga``): the executor and its state stores.

:class:`SagaService` (run / resume / signal, contract ``foundation.resiliant.saga.ISagaService``)
checkpoints every step to :class:`PgSagaRepository` (``resiliant_saga_state``, shared with
taas-server-js) - crash-resume, signals by business key, compensation in reverse order.
:class:`MemorySagaRepository` is for unit tests. Builders: ``factory.py``.
"""

from .factory import SagaFactory, build_saga_repository, build_saga_service
from .saga_repository import MemorySagaRepository, PgSagaRepository, SagaRepository
from .saga_service import SagaService

__all__ = [
    'MemorySagaRepository',
    'PgSagaRepository',
    'SagaFactory',
    'SagaRepository',
    'SagaService',
    'build_saga_repository',
    'build_saga_service',
]
