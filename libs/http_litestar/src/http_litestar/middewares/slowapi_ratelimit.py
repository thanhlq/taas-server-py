"""Per-route rate limiting for Litestar, mirroring the FastAPI adapter.

The framework-agnostic ``@get(..., ratelimit='3/minute')`` decorator records a
limit string on each :class:`platform_core.http.Route`. The FastAPI adapter
enforces it via ``slowapi`` (which only works on Starlette ``Request`` objects).
Litestar has its own request model, so ``slowapi``'s endpoint-wrapping approach
does not apply.

This module provides a Litestar-native equivalent built on the same underlying
``limits`` library that ``slowapi_advanced`` uses, so the two framework variants
share storage, strategy, and limit semantics:

* :func:`setup_litestar_rate_limiting` builds a shared limiter (Redis or
  in-memory) and stashes it on ``app.state``.
* :func:`rate_limit_guard` is attached to every route that declares a
  ``ratelimit``; it reads the per-route limit from ``route_handler.opt`` and
  enforces it, raising :class:`~litestar.exceptions.TooManyRequestsException`
  (HTTP 429) when the limit is exceeded.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import anyio.to_thread
from limits import RateLimitItem, parse
from limits.storage import storage_from_string
from limits.strategies import STRATEGIES, RateLimiter
from litestar.exceptions import TooManyRequestsException
from platform_core.cli import cli_print_info
from platform_core.config.ratelimit import RateLimitConfig
from platform_core.config.redis_config import RedisConfig

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.connection import ASGIConnection
    from litestar.handlers.base import BaseRouteHandler

__all__ = (
    'RateLimiterState',
    'rate_limit_guard',
    'setup_litestar_rate_limiting',
)

# Key under which the shared limiter is stored on ``app.state``.
STATE_KEY = 'rate_limiter'

# Default strategy — matches ``slowapi_advanced``'s default so both adapters
# count requests identically.
_DEFAULT_STRATEGY = 'fixed-window'
_DEFAULT_KEY_PREFIX = 'LIMITER'


@dataclass
class RateLimiterState:
    """Shared rate-limiter state attached to ``app.state``."""

    limiter: RateLimiter
    enabled: bool = True
    key_prefix: str = _DEFAULT_KEY_PREFIX


def _client_ip(connection: ASGIConnection) -> str:
    """Return the client IP for *connection* (``127.0.0.1`` when unknown).

    Honours ``X-Forwarded-For`` to match ``slowapi_advanced.util.get_ipaddr``.
    """
    forwarded = connection.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    client = connection.client
    if client and client.host:
        return client.host
    return '127.0.0.1'


def setup_litestar_rate_limiting(app: Litestar, config: RateLimitConfig) -> RateLimiterState:
    """Build a shared limiter from *config* and attach it to ``app.state``.

    Uses Redis when ``config.provider`` is ``redis`` (shared across workers),
    otherwise an in-process memory backend. The same ``limits`` storage and
    ``fixed-window`` strategy as the FastAPI/slowapi path are used so limits
    behave identically across frameworks.
    """
    if config.provider == 'memory':
        storage_uri = 'memory://'
    else:
        storage_uri = RedisConfig(
            host=config.redis_host,
            sentinel_master_name=config.redis_master_name,
            password=config.redis_password,
        ).get_all_in_one_redis_url()

    cli_print_info(
        f'Setting up Litestar rate limiting with provider={config.provider}, '
        f'url={storage_uri}'
    )

    storage = storage_from_string(storage_uri)
    limiter = STRATEGIES[_DEFAULT_STRATEGY](storage)
    state = RateLimiterState(limiter=limiter, enabled=config.enabled)
    app.state[STATE_KEY] = state
    return state


def _get_state(connection: ASGIConnection) -> Optional[RateLimiterState]:
    try:
        return connection.app.state.get(STATE_KEY)
    except (AttributeError, KeyError):
        return None


async def rate_limit_guard(
    connection: ASGIConnection, route_handler: BaseRouteHandler
) -> None:
    """Litestar guard enforcing the route's ``ratelimit`` declaration.

    Attached only to handlers that declare a limit (see
    ``http_litestar.adapters._controller``). No-ops when rate limiting is not
    configured or disabled, keeping the route fully functional in dev/test.
    """
    limit_str = route_handler.opt.get('ratelimit')
    if not limit_str:
        return

    state = _get_state(connection)
    if state is None or not state.enabled:
        return

    item: RateLimitItem = parse(limit_str)
    # Bucket the count per client + route + limit so distinct routes (and
    # distinct limits) never share a window. ``ratelimit_key`` is the route's
    # path template, set by the adapter alongside ``ratelimit``.
    bucket = route_handler.opt.get('ratelimit_key') or route_handler.name or ''
    identifiers = (state.key_prefix, _client_ip(connection), bucket, limit_str)

    allowed = await anyio.to_thread.run_sync(state.limiter.hit, item, *identifiers)
    if allowed:
        return

    # Compute Retry-After from the window reset time.
    reset_at, _remaining = await anyio.to_thread.run_sync(
        state.limiter.get_window_stats, item, *identifiers
    )
    import time as _time

    retry_after = max(0, math.ceil(reset_at - _time.time()))
    raise TooManyRequestsException(
        detail=f'Rate limit exceeded: {limit_str}',
        headers={'Retry-After': str(retry_after)},
    )
