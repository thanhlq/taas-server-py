"""Load idempotency settings from environment variables (``IDEMPOTENCY_*``).

| Variable | Default | Meaning |
| --- | --- | --- |
| ``IDEMPOTENCY_BACKEND`` | ``postgres`` | ``postgres`` or ``redis`` (``IdempotencyBackend``) |
| ``IDEMPOTENCY_REDIS_HOST`` | ``TAAS_CACHE_REDIS_HOST`` | ``redis://host:port/db`` (or sentinel host list) |
| ``IDEMPOTENCY_REDIS_PASSWORD`` | ``TAAS_CACHE_REDIS_PASSWORD`` | Redis password |
| ``IDEMPOTENCY_REDIS_KEY_PREFIX`` | ``idempotency`` | Namespace of the Redis keys |
| ``IDEMPOTENCY_TTL_DAYS`` | ``30`` | Retention (Redis: key TTL; Postgres: cleanup age) |
| ``IDEMPOTENCY_CLEANUP_BATCH_SIZE`` | ``500`` | Postgres cleanup batch |
| ``IDEMPOTENCY_ENABLE_METRICS`` / ``_LOG_DUPLICATES`` / ``_STRICT_MODE`` | ``true`` / ``true`` / ``false`` | Behaviour flags |
| ``IDEMPOTENCY_LEASE_MS`` | ``60000`` | Redis: lease of a key while its work runs |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from foundation.config.cache import CacheConfig
from foundation.config.redis_config import RedisConfig
from foundation.resiliant.idempotency import IdempotencyBackend, IdempotencyConfig
from foundation.utils.env_utils import get_env


@dataclass
class IdempotencySettings:
    """Idempotency configuration read from the environment."""

    BACKEND: str = field(default_factory=get_env('IDEMPOTENCY_BACKEND', IdempotencyBackend.POSTGRES.value))
    REDIS_HOST: str = field(default_factory=get_env('IDEMPOTENCY_REDIS_HOST', ''))
    """Empty = the cache Redis (``TAAS_CACHE_REDIS_HOST``)."""
    REDIS_PASSWORD: str = field(default_factory=get_env('IDEMPOTENCY_REDIS_PASSWORD', ''))
    REDIS_KEY_PREFIX: str = field(default_factory=get_env('IDEMPOTENCY_REDIS_KEY_PREFIX', 'idempotency'))
    TTL_DAYS: int = field(default_factory=get_env('IDEMPOTENCY_TTL_DAYS', 30, int))
    CLEANUP_BATCH_SIZE: int = field(default_factory=get_env('IDEMPOTENCY_CLEANUP_BATCH_SIZE', 500, int))
    ENABLE_METRICS: bool = field(default_factory=get_env('IDEMPOTENCY_ENABLE_METRICS', True))
    LOG_DUPLICATES: bool = field(default_factory=get_env('IDEMPOTENCY_LOG_DUPLICATES', True))
    STRICT_MODE: bool = field(default_factory=get_env('IDEMPOTENCY_STRICT_MODE', False))
    LEASE_MS: int = field(default_factory=get_env('IDEMPOTENCY_LEASE_MS', 60_000, int))

    def get_config(self) -> IdempotencyConfig:
        return IdempotencyConfig(
            backend=IdempotencyBackend(self.BACKEND.strip().lower()),
            redis_key_prefix=self.REDIS_KEY_PREFIX,
            ttl_days=self.TTL_DAYS,
            cleanup_batch_size=self.CLEANUP_BATCH_SIZE,
            enable_metrics=self.ENABLE_METRICS,
            log_duplicates=self.LOG_DUPLICATES,
            strict_mode=self.STRICT_MODE,
            lease_ms=self.LEASE_MS,
        )

    def get_redis_config(self) -> RedisConfig:
        """Connection of the Redis store; defaults to the cache Redis."""
        cache = CacheConfig()
        return RedisConfig(
            host=self.REDIS_HOST or cache.redis_host,
            password=self.REDIS_PASSWORD or cache.redis_password or None,
            key_prefix=self.REDIS_KEY_PREFIX,
            sentinel_master_name=cache.redis_master_name,
        )


@lru_cache(maxsize=1)
def get_idempotency_settings() -> IdempotencySettings:
    return IdempotencySettings()


def get_idempotency_config(settings: IdempotencySettings | None = None) -> IdempotencyConfig:
    """The validated :class:`IdempotencyConfig` from ``settings`` (default: environment)."""
    return (settings or get_idempotency_settings()).get_config()
