# Integration of slowapi_advanced for rate limiting in FastAPI

from platform_core.config.redis_config import RedisConfig
from platform_core.config import Settings
from slowapi_advanced.errors import RateLimitExceeded
from slowapi_advanced.util import get_remote_address
from fastapi import FastAPI
from slowapi_advanced import Limiter, _rate_limit_exceeded_handler


def setup_fastapi_rate_limiting(app: FastAPI, settings: Settings):
    """
    Set up rate limiting for the FastAPI application using slowapi_advanced.
    """

    # if sentinel redis:
    # url format: redis+sentinel://host:port[,host:port...]/service-name

    server_settings = settings.server

    url = RedisConfig(
        host=server_settings.RATE_LIMIT_REDIS_HOST,
        sentinel_master_name=server_settings.RATE_LIMIT_REDIS_MASTER_NAME,
        password=server_settings.RATE_LIMIT_REDIS_PASSWORD,
    ).get_all_in_one_redis_url()

    limiter = Limiter(
        key_func=get_remote_address, storage_uri=url, default_limits=['5/minute']
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
