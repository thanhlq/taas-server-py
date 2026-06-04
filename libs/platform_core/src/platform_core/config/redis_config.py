from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple

# Simple / fallback defaults for Redis connection parameters.
REDIS_HOST_DEFAULT = 'redis'
REDIS_PORT_DEFAULT = 6379
REDIS_CLUSTER_PASSWORD_DEFAULT = None


@dataclass
class RedisConfig:
    """
    The purpose is to have a single source of configurations for redis deployment modes as:
      - single instance
      - sentinel
      - cluster

      The mode is used to determine which client to create and test against.
    """

    mode: Optional[Literal['single', 'sentinel', 'cluster']] = None
    host: Optional[str] = None
    port: Optional[int] = None
    password: Optional[str] = None
    socket_timeout: float = 0.5
    ttl: int = 60
    key_prefix: str = 'api-cache'
    db: Optional[int] = 0
    sentinel_master_name: Optional[str] = None
    # others
    encoding: str = 'utf-8'
    decode_responses: bool = True

    def __post_init__(self):
        if not self.mode:
            self.mode = 'single'  # Default to single mode if not specified
        if self.mode == 'single':
            if not self.host:
                self.host = REDIS_HOST_DEFAULT
            # For single mode, we expect a single host:port pair.
            if ',' in self.host:
                raise ValueError(
                    'For single mode, hosts should be a single host:port pair.'
                )
        elif self.mode == 'sentinel':
            # For sentinel and cluster modes, we expect multiple host:port pairs.
            if not self.host:
                raise ValueError(
                    'For sentinel mode, hosts should be provided as a comma-separated list of host:port pairs.'
                )
            if ',' not in self.host:
                raise ValueError(
                    'For sentinel mode, hosts should be a comma-separated list of host:port pairs.'
                )
        elif self.mode == 'cluster':
            if not self.host:
                raise ValueError(
                    'For cluster mode, hosts should be provided as a comma-separated list of host:port pairs.'
                )
            if self.password is None:
                self.password = REDIS_CLUSTER_PASSWORD_DEFAULT
            if ',' not in self.host:
                raise ValueError(
                    'For cluster mode, hosts should be a comma-separated list of host:port pairs.'
                )
        else:
            raise ValueError(
                "Invalid mode. Expected 'single', 'sentinel', or 'cluster'."
            )

    def get_sentinel_master_name(self) -> str:
        if not self.sentinel_master_name:
            raise ValueError("Sentinel master name must be provided for sentinel mode.")
        return self.sentinel_master_name

    def get_host(self) -> str:
        return self.host or REDIS_HOST_DEFAULT

    def get_port(self) -> int:
        return self.port or REDIS_PORT_DEFAULT

    def get_sentinel_hosts(self) -> List[Tuple[str, int]]:
        """Parse the host string into a list of (host, port) tuples."""
        return _parse_sentinel_hosts(self.get_host())

    def get_cluster_hosts(self) -> List[Tuple[str, int]]:
        """Parse the host string into a list of (host, port) tuples for cluster mode."""
        return _parse_sentinel_hosts(self.get_host())

    def get_all_in_one_redis_url(self) -> str:
        """
        Construct a Redis URL that can be used by redis-py clients.
        Also support of password included in the URL if provided.
        """
        if self.mode == 'single':
            if self.password:
                return f'redis://:{self.password}@{self.get_host()}:{self.get_port()}/{self.db}'
            return f'redis://{self.get_host()}:{self.get_port()}/{self.db}'
        elif self.mode in ['sentinel', 'cluster']:
            # For sentinel and cluster modes, we can return a comma-separated list of hosts.
            if self.password:
                return f'redis+{self.mode}://:{self.password}@{self.get_host()}/?db={self.db}'
            return f'redis+{self.mode}://{self.get_host()}/?db={self.db}'
        else:
            raise ValueError(
                "Invalid mode. Expected 'single', 'sentinel', or 'cluster'."
            )

    def __str__(self) -> str:
        return f'RedisConfig(mode={self.mode}, host={self.host}, port={self.port}, password={"***" if self.password else None}, db={self.db}, sentinel_master_name={self.sentinel_master_name})'


def _parse_sentinel_hosts(raw: str) -> List[Tuple[str, int]]:
    """
    Parse "host:port,host:port,..." into [(host, port), ...].

    Examples:
        >>> _parse_sentinel_hosts("host1:26379,host2:26379")

            [("host1", 26379), ("host2", 26379)]
    """
    out: List[Tuple[str, int]] = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.partition(':')
        out.append((host, int(port) if port else 26379))
    return out
