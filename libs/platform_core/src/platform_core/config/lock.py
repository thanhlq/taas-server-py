from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.utils.env_utils import get_env

__all__ = ('DistributedLockConfig',)


CONFIG_PREFIX = 'TAAS'


@dataclass
class DistributedLockConfig:
    """Configuration for distributed locks.

    Mirrors the ``DISTRIBUTED_LOCK_*`` fields previously defined inline on
    :class:`AppSettings`. Adapters consume this to build their concrete
    lock client (e.g. Redlock over Redis) — same env vars work across
    frameworks.
    """

    enabled: bool = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_ENABLED', False)
    )
    """Master switch. When False, adapters skip installing the lock client."""

    provider: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_PROVIDER', 'redis')
    )
    """Storage backend: ``redis`` is the only currently supported provider."""

    # ---- Redis backend ------------------------------------------------------
    redis_host: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_REDIS_HOST', 'redis://redis:6379/0'
        )
    )
    """Redis URL or sentinel host list. For single-node use
    ``redis://host:port/db``; for sentinel pass a comma-separated host:port
    list and set :attr:`redis_master_name`."""

    redis_password: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_REDIS_PASSWORD', ''
        )
    )
    """Empty string = no auth."""

    redis_master_name: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_REDIS_MASTER_NAME', 'lock-master'
        )
    )
    """Redis Sentinel master name. Ignored when :attr:`redis_host` is a plain
    ``redis://`` URL."""

    # ---- Lock behaviour ----------------------------------------------------
    ttl: int = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_TTL', 60, int
        )
    )
    """Default lock lifetime, in seconds. The lock auto-releases after this
    even if the holder crashes — set this generously above your worst-case
    critical-section duration."""

    key_prefix: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_DISTRIBUTED_LOCK_KEY_PREFIX', 'distributed_lock'
        )
    )
    """Prefix for keys written to the storage backend — lets you share one
    Redis with other apps without collisions."""
