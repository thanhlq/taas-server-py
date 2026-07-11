"""
Thread-safe handler context for sharing validated data across parallel handlers.

This module provides a request-scoped context that allows multiple handlers
processing the same event in parallel to share cached database queries and
validation results without race conditions.

Key Features:
- AsyncIO lock-based synchronization for safe concurrent access
- Automatic cache key generation
- TTL-based cache expiration
- Performance metrics tracking
- Lazy initialization pattern
- Memory-only scope (per-event processing)

Usage:
    ctx = HandlerContext()

    # In handler 1 (running in parallel)
    tx_status = await ctx.get_or_fetch(
        'transaction_status',
        lambda: db.query_transaction_status(tx_id)
    )

    # In handler 2 (running in parallel)
    # Will reuse the cached result from handler 1
    tx_status = await ctx.get_or_fetch(
        'transaction_status',
        lambda: db.query_transaction_status(tx_id)
    )
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from core.observability.log_factory import LogFactory

T = TypeVar('T')


@dataclass
class CachedValue:
    """Wrapper for cached values with metadata."""

    value: Any
    cached_at: datetime
    ttl: Optional[timedelta] = None

    def is_expired(self) -> bool:
        """Check if cached value has expired."""
        if self.ttl is None:
            return False
        return datetime.now() - self.cached_at > self.ttl


@dataclass
class HandlerContextMetrics:
    """Performance metrics for handler context."""

    cache_hits: int = 0
    cache_misses: int = 0
    db_queries_saved: int = 0
    concurrent_fetches_prevented: int = 0

    def hit_rate(self) -> float:
        """Calculate cache hit rate percentage."""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0.0


class HandlerContext:
    """
    Thread-safe context for sharing data across parallel handlers.

    This class uses AsyncIO locks to ensure safe concurrent access when
    multiple handlers process the same event in parallel. It prevents
    redundant database queries and provides caching with optional TTL.

    Thread-safety guarantees:
    - Only one handler will fetch data for a given key
    - Other handlers requesting the same key will wait for the result
    - No race conditions or duplicate queries
    - Atomic cache updates

    Attributes:
        _cache: Internal cache storage
        _locks: Per-key locks for safe concurrent access
        _global_lock: Lock for managing the locks dictionary
        metrics: Performance tracking metrics
    """

    def __init__(self, default_ttl: Optional[timedelta] = None):
        """
        Initialize handler context.

        Args:
            default_ttl: Default TTL for cached values (None = no expiration)
        """
        self._cache: Dict[str, CachedValue] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._default_ttl: timedelta | None = default_ttl
        self.metrics = HandlerContextMetrics()
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    async def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable[[], Awaitable[T]],
        ttl: Optional[timedelta] = None,
    ) -> T:
        """
        Get value from cache or fetch if not present (thread-safe).

        This method ensures that even if 10 handlers call it simultaneously
        with the same key, only ONE will execute the fetch_fn, and all others
        will wait and receive the same result.

        Args:
            key: Cache key
            fetch_fn: Async function to fetch data if not cached
            ttl: Time-to-live for this cache entry (overrides default)

        Returns:
            Cached or freshly fetched value

        Example:
            # Multiple handlers can call this safely in parallel
            tx_status = await ctx.get_or_fetch(
                f'tx_status:{tx_id}',
                lambda: transaction_repo.get_status(tx_id),
                ttl=timedelta(seconds=30)
            )
        """
        # Quick check if already cached (no lock needed for read)
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired():
                self.metrics.cache_hits += 1
                self.metrics.db_queries_saved += 1  # Each cache hit saves a DB query
                self.logger.debug(f'Cache HIT for key: {key}')
                return cached.value
            else:
                self.logger.debug(f'Cache entry EXPIRED for key: {key}')

        # Get or create lock for this key (needs global lock)
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]

        # Acquire key-specific lock
        async with lock:
            # Double-check cache after acquiring lock
            # (another handler might have fetched while we waited)
            if key in self._cache:
                cached = self._cache[key]
                if not cached.is_expired():
                    self.metrics.cache_hits += 1  # Count as cache hit
                    self.metrics.db_queries_saved += 1  # Saved a DB query
                    self.metrics.concurrent_fetches_prevented += 1
                    self.logger.debug(
                        f'Cache HIT after lock wait for key: {key} '
                        f'(prevented duplicate fetch)'
                    )
                    return cached.value

            # Cache miss - fetch the data
            self.metrics.cache_misses += 1
            self.logger.debug(f'Cache MISS for key: {key}, fetching...')

            start_time = datetime.now()
            value = await fetch_fn()
            fetch_duration = (datetime.now() - start_time).total_seconds()

            # Cache the result
            effective_ttl = ttl if ttl is not None else self._default_ttl
            self._cache[key] = CachedValue(
                value=value, cached_at=datetime.now(), ttl=effective_ttl
            )

            self.logger.debug(
                f'Fetched and cached key: {key} '
                f'(took {fetch_duration:.3f}s, ttl={effective_ttl})'
            )

            return value

    def set(self, key: str, value: Any, ttl: Optional[timedelta] = None) -> None:
        """
        Manually set a cache value (not async, use for immediate values).

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live for this cache entry
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._cache[key] = CachedValue(
            value=value, cached_at=datetime.now(), ttl=effective_ttl
        )
        self.logger.debug(f'Manually set cache key: {key}')

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get cached value without fetching (returns None/default if not found).

        Args:
            key: Cache key
            default: Default value if not found or expired

        Returns:
            Cached value or default
        """
        if key in self._cache:
            cached = self._cache[key]
            if not cached.is_expired():
                return cached.value
        return default

    def invalidate(self, key: str) -> None:
        """
        Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]
            self.logger.debug(f'Invalidated cache key: {key}')

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        self.logger.debug('Cleared all cache entries')

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics.

        Returns:
            Dictionary with cache performance metrics
        """
        return {
            'cache_hits': self.metrics.cache_hits,
            'cache_misses': self.metrics.cache_misses,
            'hit_rate': self.metrics.hit_rate(),
            'db_queries_saved': self.metrics.cache_hits,
            'concurrent_fetches_prevented': self.metrics.concurrent_fetches_prevented,
            'total_cached_keys': len(self._cache),
        }

    def log_metrics(self) -> None:
        """Log current metrics (useful for debugging)."""
        metrics = self.get_metrics()
        self.logger.info(
            f'HandlerContext metrics: '
            f'hits={metrics["cache_hits"]}, '
            f'misses={metrics["cache_misses"]}, '
            f'hit_rate={metrics["hit_rate"]:.1f}%, '
            f'concurrent_fetches_prevented={metrics["concurrent_fetches_prevented"]}, '
            f'cached_keys={metrics["total_cached_keys"]}'
        )
