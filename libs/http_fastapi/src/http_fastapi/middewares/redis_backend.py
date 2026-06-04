from typing import Optional, Tuple

from fastapi_cache import Backend
from platform_core import BaseService
from platform_core.config import get_settings
from platform_core.config.cache import CacheConfig
from platform_core.config.settings import Settings
from store_redis import Redis, RedisStore, create_redis_client

_SCAN_COUNT = 500


async def _scan_unlink(redis, pattern: str) -> int:
    """Delete keys matching `pattern` without blocking Redis.

    Replaces the fastapi-cache `RedisBackend.clear(namespace=...)` pattern
    which uses `KEYS + DEL` in a Lua script — both O(N) over the whole
    keyspace and blocking. SCAN is cursor-based; UNLINK is async on the
    server side. While this runs Redis stays responsive to PUBLISH and other
    commands.
    """
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=_SCAN_COUNT)
        if keys:
            await redis.unlink(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    return deleted


class FastapiCacheBackend(Backend, BaseService):
    # _redis_client: aioredis.Redis
    _redis_store: RedisStore
    _cache_config: CacheConfig

    def __init__(self, config: Optional[CacheConfig] = None):
        if config is None:
            settings: Settings = get_settings()
            self._cache_config = settings.app.get_cache_config()
        else:
            self._cache_config = config
        _redis_client = create_redis_client(self._cache_config.get_redis_config())
        self._redis_store = RedisStore(_redis_client)

    @property
    def redis_store(self) -> RedisStore:
        return self._redis_store

    @property
    def cache_config(self) -> CacheConfig:
        return self._cache_config

    @property
    def redis(self) -> Redis:
        return self._redis_store.redis

    async def start(self) -> 'FastapiCacheBackend':
        # try to ping Redis to ensure it's available before starting the service
        await self._redis_store.ping()
        self.logger.info('🧰 🟢 Redis cache connection established for fastapi cache')
        return self

    async def stop(self):
        if self._redis_store:
            await self._redis_store.shutdown()

    async def get(self, key: str) -> Optional[bytes]:
        return await self.redis.get(key)  # type: ignore[union-attr]

    async def set(self, key: str, value: bytes, expire: Optional[int] = None) -> None:
        await self.redis.set(key, value, ex=expire)  # type: ignore[union-attr]

    async def get_with_ttl(self, key: str) -> Tuple[int, Optional[bytes]]:
        async with self.redis.pipeline(
            transaction=not self._redis_store.is_cluster()
        ) as pipe:
            return await pipe.ttl(key).get(key).execute()  # type: ignore[union-attr,no-any-return]

    async def clear_cache(self):
        await _scan_unlink(self._redis_store.redis, '*')

    async def clear(
        self, namespace: Optional[str] = None, key: Optional[str] = None
    ) -> int:
        if namespace:
            lua = f"for i, name in ipairs(redis.call('KEYS', '{namespace}:*')) do redis.call('DEL', name); end"
            return await self.redis.eval(lua, numkeys=0)  # type: ignore[union-attr,no-any-return]
        elif key:
            return await self.redis.delete(key)  # type: ignore[union-attr]
        return 0

    # async def clear(
    #     self, namespace: Optional[str] = None, key: Optional[str] = None
    # ) -> int:
    #     # Solution 1: Use SCAN + UNLINK to delete keys matching the pattern
    #     # without blocking Redis
    #     if namespace and key:
    #         pattern = f'{namespace}:{key}'
    #     elif namespace:
    #         pattern = f'{namespace}:*'
    #     else:
    #         pattern = '*'
    #     deleted_count = await _scan_unlink(self._redis_store.redis, pattern)

    #     # Solution 2: traditional way to delete keys with KEYS + DEL (blocking, not recommended for production)
    #     # deleted_count = await super().clear(namespace=namespace, key=key)

    #     return deleted_count
