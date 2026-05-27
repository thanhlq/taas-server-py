from typing import Any, Optional
import redis.asyncio as aioredis
from platform_core.config.redis_config import (
    RedisConfig,
)
from platform_core.config import get_settings, Settings, ServerSettings

from .redis_client import create_redis_client
from .redis_client import build_redis_config_from_env


_settings: Settings = get_settings()
settings: ServerSettings = _settings.server


def get_env(key: str, default: Optional[Any] = None) -> Any:
    return getattr(settings, key, default)


def from_url(url, **kwargs):
    """Legacy method to create a Redis client from a URL."""
    return find_redis_url_4_caching(url, **kwargs)


def find_redis_url_4_caching(url: Optional[str] = None, **kwargs) -> aioredis.Redis:
    """Create a Redis client for caching purposes."""

    host = settings.API_CACHE_REDIS_HOST or url
    sentinel_master_name = settings.API_CACHE_REDIS_MASTER_NAME
    encoding = kwargs.pop('encoding', 'utf8')
    decode_responses = kwargs.pop('decode_responses', True)

    rc: RedisConfig = build_redis_config_from_env(
        host=host,
        sentinel_master_name=sentinel_master_name,
        get_env=get_env,
        encoding=encoding,
        decode_responses=decode_responses,
    )
    print(f'Creating Redis client for caching with config: {rc}')
    return create_redis_client(rc)


def find_redis_url_4_rate_limit(url, **kwargs) -> aioredis.Redis:
    """Create a Redis client for rate limiting purposes."""
    if not settings.RATE_LIMIT_ENABLED:
        raise ValueError('Rate limiting is not enabled in settings.')

    # Detect specific Redis host for rate limiting, if not provided, fallback to general Redis host
    host = settings.RATE_LIMIT_REDIS_HOST or url
    sentinel_master_name = settings.RATE_LIMIT_REDIS_MASTER_NAME
    encoding = kwargs.pop('encoding', 'utf8')
    decode_responses = kwargs.pop('decode_responses', False)

    rc: RedisConfig = build_redis_config_from_env(
        host=host,
        sentinel_master_name=sentinel_master_name,
        get_env=get_env,
        encoding=encoding,
        decode_responses=decode_responses,
    )
    print(f'Creating Redis client for rate limiting with config: {rc}')
    return create_redis_client(rc)


def find_redis_url_4_pubsub(url, **kwargs) -> aioredis.Redis:
    """Create a Redis client for websocket pub/sub purposes."""

    # Detect specific Redis host for pub/sub, if not provided, fallback to general Redis host
    host = settings.WEBSOCKET_REDIS_HOST or url
    sentinel_master_name = settings.WEBSOCKET_REDIS_MASTER_NAME
    encoding = kwargs.pop('encoding', 'utf8')
    decode_responses = kwargs.pop('decode_responses', False)

    rc: RedisConfig = build_redis_config_from_env(
        host=host,
        sentinel_master_name=sentinel_master_name,
        get_env=get_env,
        encoding=encoding,
        decode_responses=decode_responses,
    )
    print(f'Creating Redis client for pubsub with config: {rc}')
    return create_redis_client(rc)


__all__ = [
    'from_url',
    'find_redis_url_4_caching',
    'find_redis_url_4_rate_limit',
    'find_redis_url_4_pubsub',
    'RedisConfig',
    'create_redis_client',
    'build_redis_config_from_env',
]
