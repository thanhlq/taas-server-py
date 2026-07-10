import socketio

from foundation.config.wss import WebSocketConfig
from foundation.logger import logger


def build_websocket_redis_manager(
    config: WebSocketConfig,
    *,
    write_only: bool = False,
    channel: str = 'socketio',
) -> socketio.AsyncRedisManager:
    """Build a Socket.IO Redis manager from WEBSOCKET_REDIS_* settings."""

    # AsyncRedisManager wants a URL; build it from your RedisConfig so single
    # and sentinel modes share the same code path that the rest of the app uses.
    # For single-mode this is `redis://host:port/db`. For sentinel you'll need
    # a custom resolver — see "Sentinel notes" below.
    from foundation.config.redis_config import RedisConfig
    # from foundation.config.redis_client import build_redis_config_from_env

    rc: RedisConfig = RedisConfig(
        host=config.redis_host,
        sentinel_master_name=config.redis_master_name,
        password=config.redis_password,
        encoding='utf-8',
        decode_responses=False,  # socketio uses binary payloads
    )
    url = rc.get_all_in_one_redis_url(db=True)

    logger.info(f'Creating WebSocket Redis manager with URL: {url}, channel: {channel}, write_only: {write_only}')


    return socketio.AsyncRedisManager(url, channel=channel, write_only=write_only)
