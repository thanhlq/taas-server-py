from typing import Literal, Optional, List, Tuple, Callable
from dataclasses import dataclass
from typing_extensions import TypeAlias

import redis.asyncio as aioredis
import redis.asyncio.sentinel as sentinel
import redis.asyncio.cluster as redis_cluster
from redis.asyncio.cluster import ClusterNode


from platform_core.config.redis_config import RedisConfig

type GET_ENV = Callable[[str, Optional[str]], str]


def create_single_redis_client(
    config: RedisConfig,
) -> aioredis.Redis:
    """Direct Redis connection — use against a standalone instance."""

    if 'redis://' not in config.get_host():
        host = f'redis://{config.host}:{config.port}'

    return aioredis.from_url(
        f'{host}',
        password=config.password,
        db=config.db,
        socket_timeout=config.socket_timeout,
        encoding=config.encoding,
        decode_responses=config.decode_responses,
    )


def _build_sentinel(
    config: RedisConfig,
) -> sentinel.Sentinel:
    addrs = config.get_sentinel_hosts()
    sentinel_pw = config.password
    sentinel_kwargs = {'password': sentinel_pw} if sentinel_pw else {}
    return sentinel.Sentinel(
        addrs,
        socket_timeout=config.socket_timeout,
        sentinel_kwargs=sentinel_kwargs,
        password=config.password,
        db=config.db,
        # encoding=config.encoding,
        # decode_responses=config.decode_responses,
    )


def create_sentinel_client(config: RedisConfig) -> aioredis.Redis:
    if config.mode is None:
        config.mode = 'sentinel'

    s = _build_sentinel(config)
    return s.master_for(
        config.get_sentinel_master_name(),
        socket_timeout=config.socket_timeout,
        db=config.db,
        password=config.password,
    )


def create_cluster_client(config: RedisConfig) -> redis_cluster.RedisCluster:
    if config.mode is None:
        config.mode = 'cluster'

    nodes: list[tuple[str, int]] = config.get_cluster_hosts()

    cluster_nodes: list[ClusterNode] = [
        ClusterNode(host=node[0], port=node[1]) for node in nodes
    ]

    rc = redis_cluster.RedisCluster(
        startup_nodes=cluster_nodes,
        decode_responses=True,
        encoding=config.encoding,
        password=config.password,
        db=config.db,  # type: ignore
    )

    return rc


def create_redis_client(config: RedisConfig) -> aioredis.Redis:
    if config.mode == 'single':
        redis = create_single_redis_client(config)
    elif config.mode == 'sentinel':
        redis = create_sentinel_client(config)
    else:
        raise ValueError(f'Unsupported mode: {config.mode}')
    print(f'Created Redis client with config: {config}')
    return redis


def build_redis_config_from_env(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    mode: Optional[str] = None,
    sentinel_master_name: Optional[str] = None,
    **kwargs,
) -> RedisConfig:
    """
    Should use this function to build RedisConfig from environment variables instead of directly accessing env vars in the code,
    This function will try to detect the mode of deployment and build the config accordingly
        - single (default)
        - sentinel
        - cluster
    """

    if mode is None:
        mode = 'sentinel' if ',' in (host or '') else 'single'

    if mode == 'sentinel' and sentinel_master_name is None:
        raise ValueError('Sentinel master name must be provided for sentinel mode.')

    rc = RedisConfig(
        mode=mode,  # type: ignore
        host=host,
        port=port,
        sentinel_master_name=sentinel_master_name,
        **kwargs,
    )
    return rc
