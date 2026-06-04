import logging

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.coder import PickleCoder
from http_fastapi.middewares.cache_key_builer import custom_cache_key_builder
from http_fastapi.middewares.redis_backend import FastapiCacheBackend
from platform_core.config import get_settings
from platform_core.exceptions.report_error import report_error
from platform_core.facade.cache import ICacheService
from platform_core.state.service_registry import register_service


async def initFastapiCache():
    _settings = get_settings()
    _cache_config = _settings.app.get_cache_config()
    logger = logging.getLogger('FastAPICache')

    try:
        # If caching is disabled, initialize with in-memory backend
        if not _cache_config.enabled:
            logger.info('Initializing Fastapi Cache with in-memory backend')
            FastAPICache.init(
                backend=InMemoryBackend(),
                prefix=_cache_config.key_prefix,
                expire=_cache_config.ttl,
                key_builder=custom_cache_key_builder,
                coder=PickleCoder,
                enable=False,
            )
            return

        # Try to connect to Redis
        try:
            # see https://github.com/long2ice/fastapi-cache/blob/main/examples/redis/main.py
            # pool = ConnectionPool.from_url(url=settings.REDIS_HOST)
            # redis_client = redis.Redis(connection_pool=pool)
            # Test the connection
            # await redis_client.set('prj-api-ping', now_as_iso(), ex=120)

            backend = register_service(FastapiCacheBackend, FastapiCacheBackend(_cache_config))
            # also register a cache service
            register_service(ICacheService, backend.redis_store)
            await backend.start()  # Start the Redis backend service

            # Redis cache with Redis backend
            FastAPICache.init(
                backend=backend,
                prefix=_cache_config.key_prefix,
                expire=_cache_config.ttl,
                key_builder=custom_cache_key_builder,
                coder=PickleCoder,
                enable=_cache_config.enabled,
            )
            logger.info('🌐 🧰  Fast API Cache initialized with Redis backend')
        except Exception as redis_error:
            report_error(redis_error, title='Error initializing FastAPI Cache', extra_context={'redis_host': _cache_config.redis_host})
            logger.warning(
                f'Failed to connect to Redis: {redis_error}. Falling back to in-memory cache.'
            )

            # Fallback to in-memory cache if Redis is not available
            FastAPICache.init(
                backend=InMemoryBackend(),
                prefix=_cache_config.key_prefix,
                expire=_cache_config.ttl,
                key_builder=custom_cache_key_builder,
                coder=PickleCoder,
                enable=_cache_config.enabled,
            )
    except Exception as e:
        logger.error(f'Error initializing FastAPICache: {e}')
        # Initialize with in-memory backend as a final fallback
        FastAPICache.init(
            backend=InMemoryBackend(),
            prefix=_cache_config.key_prefix,
            expire=_cache_config.ttl,
            key_builder=custom_cache_key_builder,
            coder=PickleCoder,
            enable=_cache_config.enabled,
        )
