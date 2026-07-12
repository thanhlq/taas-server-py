from foundation.config.cache import CacheConfig
from foundation.facade.cache import ICacheService
from foundation.state import register_service

from .redis_client import create_redis_client
from .redis_store import RedisStore


class RedisCacheServiceFactory:
    """Factory for creating RedisCacheService instances."""

    @staticmethod
    def create(_cache_config: CacheConfig) -> 'ICacheService':
        """Create a new RedisCacheService instance and register it to service registry."""
        _redis_client = create_redis_client(_cache_config.get_redis_config())
        _redis_store = RedisStore(_redis_client)
        register_service(ICacheService, _redis_store)
        return _redis_store
