import functools
from typing import Any, Callable

from cachetools import TTLCache, keys
from platform_core.config import get_settings
from platform_core.config.settings import Settings

_T = Any

def a_ttl_cache_ignore_1st_arg(func=None, *, size: int = 0, ttl: int = 0) -> Any:
    """
    Async TTL cache that ignores the first argument (e.g. self) — keyed on the
    rest. Use it on a coroutine method whose result depends on its arguments but
    not on the instance (e.g. a service method that doesn't use self), so calls
    with different first args but same trailing args share cache entries.

    Example usage::
        @a_ttl_cache_ignore_1st_arg
        async def fetch(self, key): ...

        @a_ttl_cache_ignore_1st_arg(ttl=300, size=10)
        async def fetch(self, key): ...

    """
    def decorator(fn: Callable):
        settings: Settings = get_settings()
        cache: TTLCache = TTLCache(
            maxsize=size if size > 0 else settings.app.CACHE_LRU_SIZE,
            ttl=ttl if ttl > 0 else settings.app.CACHE_EXPIRES_AFTER,
        )

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            cache_key = keys.hashkey(args[1:], **kwargs)
            if cache_key in cache:
                return cache[cache_key]
            result = await fn(*args, **kwargs)
            cache[cache_key] = result
            return result
        return wrapper

    # Bare usage: @async_cache_ttl_ignore_first_arg
    if callable(func):
        return decorator(func)
    # Parameterized usage: @async_cache_ttl_ignore_first_arg(ttl=..., size=...)
    return decorator

def a_ttl_cache_ignore_all_args(func=None, *, size: int = 0, ttl: int = 0) -> Any:
    """Async TTL cache that ignores ALL arguments — a single shared entry.

    The async counterpart of :func:`cache_lru_ignore_all_args`. Use it on a
    coroutine whose result does not depend on any of its arguments (e.g. a
    global, user-independent upstream fan-out), so every call shares one cache
    entry under a constant key.

    Unlike the sync ``cache_lru_ignore_all_args``, this awaits the coroutine and
    caches the *result*, not the coroutine object (a cached coroutine can only be
    awaited once). It also works both bare and parameterized::

        @a_ttl_cache_ignore_all_args
        async def fetch_all(self): ...

        @a_ttl_cache_ignore_all_args(ttl=300, size=10)
        async def fetch_all(self): ...
    """
    def decorator(fn: Callable):
        settings: Settings = get_settings()
        cache: TTLCache = TTLCache(
            maxsize=size if size > 0 else settings.app.CACHE_LRU_SIZE,
            ttl=ttl if ttl > 0 else settings.app.CACHE_EXPIRES_AFTER,
        )
        # print(f"⚡️ Initialized async TTL cache for {fn.__name__} with size={cache.maxsize} and ttl={cache.ttl} seconds")
        static_key = 'static_key'

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if static_key in cache:
                return cache[static_key]
            result = await fn(*args, **kwargs)
            cache[static_key] = result
            return result
        return wrapper

    # Bare usage: @async_cache_ttl_ignore_all_arg
    if callable(func):
        return decorator(func)
    # Parameterized usage: @async_cache_ttl_ignore_all_arg(ttl=..., size=...)
    return decorator
