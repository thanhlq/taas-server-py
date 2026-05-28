from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.utils.env_utils import get_env

__all__ = ('RateLimitConfig',)


CONFIG_PREFIX = 'TAAS'


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Mirrors the ``RATE_LIMIT_*`` fields previously defined inline on
    :class:`AppSettings`. Adapters (fastapi, litestar, ...) consume this to
    build their concrete limiter — keeping the knobs in one place means the
    same env vars work across frameworks.
    """

    enabled: bool = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_RATE_LIMIT_ENABLED', True)
    )
    """Master switch. When False, adapters skip installing the limiter entirely."""

    provider: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_RATE_LIMIT_PROVIDER', 'redis')
    )
    """Storage backend: ``redis`` (shared across processes) or ``memory``
    (in-process; only safe for single-worker dev / tests)."""

    # ---- Redis backend ------------------------------------------------------
    redis_host: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_RATE_LIMIT_REDIS_HOST', 'redis://redis:6379/0'
        )
    )
    """Redis URL or sentinel host list. For single-node use
    ``redis://host:port/db``; for sentinel pass a comma-separated host:port
    list and set :attr:`redis_master_name`."""

    redis_password: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_RATE_LIMIT_REDIS_PASSWORD', '')
    )
    """Empty string = no auth."""

    redis_master_name: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_RATE_LIMIT_REDIS_MASTER_NAME', 'rate-master'
        )
    )
    """Redis Sentinel master name. Ignored when :attr:`redis_host` is a plain
    ``redis://`` URL."""

    # ---- Limit defaults ----------------------------------------------------
    default_limits: list[str] = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_RATE_LIMIT_DEFAULT', ['5/minute']
        )
    )
    """Limits applied to every route that doesn't declare its own
    ``ratelimit=`` — e.g. ``["5/minute"]``, or ``["1000/hour", "100/minute"]``
    for layered caps. ``get_env`` parses the env var as a JSON list."""

    ttl: int = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_RATE_LIMIT_TTL', 60, int)
    )
    """Default window size in seconds. Currently informational; the actual
    window comes from the limit string (``5/minute`` ⇒ 60s)."""

    key_prefix: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_RATE_LIMIT_KEY_PREFIX', 'rate_limit'
        )
    )
    """Prefix for keys written to the storage backend — lets you share one
    Redis with other apps without collisions."""
