from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.config.redis_config import RedisConfig
from platform_core.utils.env_utils import get_env

__all__ = ('CacheConfig',)


CONFIG_PREFIX = 'TAAS'


@dataclass
class CacheConfig:
    """Configuration for response / object cache.

    Mirrors the ``CACHE_*`` fields previously defined inline on
    :class:`AppSettings`. Adapters consume this to build their concrete
    cache client — same env vars work across frameworks.
    """

    enabled: bool = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_CACHE_ENABLED', True)
    )
    """Master switch. When False, adapters skip installing the cache."""

    provider: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_CACHE_PROVIDER', 'redis')
    )
    """Storage backend: ``redis`` (shared across processes) or ``memory``
    (in-process; only safe for single-worker dev / tests)."""

    # ---- Redis backend ------------------------------------------------------
    redis_host: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_CACHE_REDIS_HOST', 'redis://redis:6379/0'
        )
    )
    """Redis URL or sentinel host list. For single-node use
    ``redis://host:port/db``; for sentinel pass a comma-separated host:port
    list and set :attr:`redis_master_name`."""

    redis_password: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_CACHE_REDIS_PASSWORD', '')
    )
    """Empty string = no auth."""

    redis_master_name: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_CACHE_REDIS_MASTER_NAME', 'cache-master'
        )
    )
    """Redis Sentinel master name. Ignored when :attr:`redis_host` is a plain
    ``redis://`` URL."""

    # ---- Cache behaviour ---------------------------------------------------
    ttl: int = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_CACHE_TTL', 60, int)
    )
    """Default time-to-live for entries, in seconds. Individual ``@cache``
    decorations can override this per-route."""

    key_prefix: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_CACHE_KEY_PREFIX', 'cache')
    )
    """Prefix for keys written to the storage backend — lets you share one
    Redis with other apps without collisions."""

    def get_redis_config(self) -> RedisConfig:
        """Return a RedisConfig object built from the Redis-related fields of this config."""
        return RedisConfig(
            host=self.redis_host,
            password=self.redis_password,
            ttl=self.ttl,
            key_prefix=self.key_prefix,
            sentinel_master_name=self.redis_master_name,
        )
