"""Cached signed URLs (taas-specs/files/decisions.md ADR-9): sign once per window, hand out the same URL.

- ``rounded_expiry(ttl)``: the expiry sits on a fixed grid (``ttl / 4`` steps) — every call within one step gets the
  same expiry, so a deterministic signature (HMAC token) gives the **same URL** (browser / CDN cache hits), and a
  URL never lives longer than ``ttl`` (at least ``3/4 · ttl``).
- ``SignedUrlCache.get_or_sign(key, exp, sign)``: keeps signed URLs until shortly before ``exp`` in the process
  (bounded LRU) and, for provider-signed URLs (``shared=True``: S3 / GCS / Azure signatures embed the signing time,
  two calls never match), in the platform cache (``CacheServiceT`` — Redis) so every API process returns the same
  URL. A cache outage only costs a new signature.

The permission check always happens **before** the cache is asked: the cache saves signing work, it never decides
who may read.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

_SHARED_RETRY_SECONDS = 30.0


def rounded_expiry(ttl: int, now: float | None = None, *, steps: int = 4) -> int:
    """Epoch seconds on a ``ttl / steps`` grid: ``floor(now / step) * step + ttl`` (lifetime in ``(ttl - step, ttl]``)."""
    step = max(int(ttl) // max(steps, 1), 1)
    current = time.time() if now is None else now
    return int(current // step) * step + int(ttl)


def _shared_cache() -> Any | None:
    try:
        from foundation.facade.cache import CacheServiceT
        from foundation.state import get_service

        return get_service(CacheServiceT)
    except Exception:  # noqa: BLE001 — no cache registered (tests, cache disabled)
        return None


class SignedUrlCache:
    """Signed URLs per ``(key, exp)`` kept until ``exp - margin``."""

    def __init__(
        self, namespace: str, *, max_entries: int = 20_000, margin: int = 60
    ) -> None:
        self.namespace = namespace
        self.max_entries = max_entries
        self.margin = margin
        self._local: OrderedDict[str, tuple[str, int]] = OrderedDict()
        self._shared_down_until = 0.0

    def _cache_key(self, key: str, exp: int) -> str:
        return f'{self.namespace}:{exp}:{key}'

    def _remember(self, cache_key: str, url: str, exp: int) -> None:
        self._local[cache_key] = (url, exp)
        self._local.move_to_end(cache_key)
        while len(self._local) > self.max_entries:
            self._local.popitem(last=False)

    async def get_or_sign(
        self,
        key: str,
        exp: int,
        sign: Callable[[], Awaitable[str]],
        *,
        shared: bool = False,
        now: float | None = None,
    ) -> str:
        current = time.time() if now is None else now
        fresh_until = exp - self.margin
        if fresh_until <= current:  # too short-lived to be worth caching
            return await sign()
        cache_key = self._cache_key(key, exp)
        hit = self._local.get(cache_key)
        if hit is not None:
            self._local.move_to_end(cache_key)
            return hit[0]
        cache = (
            _shared_cache() if shared and current >= self._shared_down_until else None
        )
        if cache is not None:
            try:
                value = await cache.get(cache_key)
                if value:
                    url = value.decode() if isinstance(value, bytes) else str(value)
                    self._remember(cache_key, url, exp)
                    return url
            except Exception as error:  # noqa: BLE001 — the cache is an optimisation
                self._shared_down_until = current + _SHARED_RETRY_SECONDS
                logger.debug('signed URL cache unavailable: %s', error)
                cache = None
        url = await sign()
        self._remember(cache_key, url, exp)
        if cache is not None:
            try:
                await cache.set(cache_key, url, expires_in=int(fresh_until - current))
            except Exception as error:  # noqa: BLE001
                self._shared_down_until = current + _SHARED_RETRY_SECONDS
                logger.debug('signed URL cache unavailable: %s', error)
        return url

    def clear(self) -> None:
        self._local.clear()

    def __len__(self) -> int:
        return len(self._local)
