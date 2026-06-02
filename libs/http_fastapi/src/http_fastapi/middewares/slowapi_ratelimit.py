# Integration of slowapi_advanced for rate limiting in FastAPI

from fastapi import FastAPI
from platform_core.config.ratelimit import RateLimitConfig
from platform_core.config.redis_config import RedisConfig
from slowapi_advanced import Limiter, _rate_limit_exceeded_handler
from slowapi_advanced.errors import RateLimitExceeded
from slowapi_advanced.middleware import SlowAPIMiddleware
from slowapi_advanced.util import get_remote_address


def setup_fastapi_rate_limiting(app: FastAPI, config: RateLimitConfig) -> None:
    """
    Set up rate limiting for the FastAPI application using slowapi_advanced.
    """

    # if sentinel redis:
    # url format: redis+sentinel://host:port[,host:port...]/service-name


    url = RedisConfig(
        host=config.redis_host,
        sentinel_master_name=config.redis_master_name,
        password=config.redis_password,
    ).get_all_in_one_redis_url()

    limiter = Limiter(
        key_func=get_remote_address, storage_uri=url, default_limits=['60000/minute']
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # Middleware applies `default_limits` to any route that does NOT have its
    # own @limiter.limit(...) wrapper. Routes declaring `ratelimit=` get
    # wrapped at registration time and are exempt from the middleware path
    # (slowapi tracks them in `_route_limits` and short-circuits in
    # `_should_exempt`).
    app.add_middleware(SlowAPIMiddleware)
