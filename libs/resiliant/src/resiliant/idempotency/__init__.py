"""Idempotency implementation: service + pluggable stores (Postgres, Redis) + settings.

Definitions (config, backend enum, store/service contracts) live in
``foundation.resiliant.idempotency``. Choose the store with ``IDEMPOTENCY_BACKEND``
(``postgres`` | ``redis``); build via ``factory.build_idempotency_service`` or
``ResiliantServiceFactory().get_idempotency_service()``.
"""

from .factory import build_idempotency_service, build_idempotency_store
from .idempotency_metrics import IdempotencyMetrics
from .idempotency_service import IdempotencyService
from .idempotency_settings import IdempotencySettings, get_idempotency_config
from .stores import PostgresIdempotencyStore, RedisIdempotencyStore

# Backward-compatible name of the Postgres store.
IdempotencyRepository = PostgresIdempotencyStore

__all__ = [
    "IdempotencyMetrics",
    "IdempotencyRepository",
    "IdempotencyService",
    "IdempotencySettings",
    "PostgresIdempotencyStore",
    "RedisIdempotencyStore",
    "build_idempotency_service",
    "build_idempotency_store",
    "get_idempotency_config",
]
