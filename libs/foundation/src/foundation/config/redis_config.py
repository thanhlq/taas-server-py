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

    mode: Optional[Literal['single', 'sentinel', 'cluster']] = 'single'
    host: Optional[str] = None
    port: Optional[int] = 6379
    user: Optional[str] = None
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
        # Also detect if the host string contains multiple hosts, which implies sentinel mode.
        # Examples:
        #   "host1:26379,host2:26379" -> sentinel mode
        #   "host:6379" -> single mode

        # if sentinel mode or cluster mode -> let as it is, do not parse the host string for embedded credentials
        self.host = self.host or REDIS_HOST_DEFAULT
        self.mode = self.mode or 'single'

        if self.mode == 'single' and ('@' in self.host or ':' in self.host):
            # Handle the case with embedded password

            if '@' in self.host:
                userinfo, hostport = self.host.split('@', 1)
            else:
                hostport = self.host
                userinfo = None

            if userinfo is not None:
                user, password = (
                    userinfo.split(':', 1) if ':' in userinfo else (None, None)
                )
                self.user = user
                self.password = password
            else:
                user = None
                password = None

            if ':' in hostport:
                host, port = hostport.rsplit(':', 1)
                self.host = host
                self.port = int(port)
            else:
                self.host = hostport

        if self.host and ',' in self.host and self.mode is None:
            # does not support cluster yet
            self.mode = (
                'sentinel'  # auto-detect sentinel mode if multiple hosts are provided
            )

    def get_sentinel_master_name(self) -> str:
        if not self.sentinel_master_name:
            raise ValueError('Sentinel master name must be provided for sentinel mode.')
        return self.sentinel_master_name

    def get_host(self) -> str:
        return self.host or REDIS_HOST_DEFAULT

    # Return host for logging without exposing the password
    # Also handle the case embedded password in the host string (e.g., redis://:password@host:port)
    def get_host_info(self) -> str:
        host_info = f'{self.get_host()}:{self.get_port()}'
        if self.password:
            host_info = f'{self.get_host()}:{self.get_port()} (password=***)'
        return host_info

    def get_port(self) -> int:
        return self.port or REDIS_PORT_DEFAULT

    def get_sentinel_hosts(self) -> List[Tuple[str, int]]:
        """Parse the host string into a list of (host, port) tuples."""
        return _parse_sentinel_hosts(self.get_host())

    def get_cluster_hosts(self) -> List[Tuple[str, int]]:
        """Parse the host string into a list of (host, port) tuples for cluster mode."""
        return _parse_sentinel_hosts(self.get_host())

    def get_all_in_one_redis_url(self, db: bool = False) -> str:
        """
        Construct a Redis URL that can be used by redis-py clients.
        Also support of password included in the URL if provided.
        """
        if self.mode == 'single':
            if self.user and self.password:
                return f'redis://{self.user}:{self.password}@{self.get_host()}:{self.get_port()}/{self.db}'
            elif self.password:
                return f'redis://:{self.password}@{self.get_host()}:{self.get_port()}/{self.db}'
            return f'redis://{self.get_host()}:{self.get_port()}/{self.db}'
        elif self.mode in ['sentinel', 'cluster']:
            # Notes:
            # - ⚠️ limits (lib): url format: sentinel_url="redis+sentinel://:redis-password@localhost:26379/mymaster",
            if self.password:
                if db:
                    return f'redis+{self.mode}://:{self.password}@{self.get_host()}/{self.db}/{self.get_sentinel_master_name()}'
                else:
                    return f'redis+{self.mode}://:{self.password}@{self.get_host()}/{self.get_sentinel_master_name()}'
            else:
                if db:
                    return f'redis+{self.mode}://{self.get_host()}/{self.db}/{self.get_sentinel_master_name()}'
                else:
                    return f'redis+{self.mode}://{self.get_host()}/{self.get_sentinel_master_name()}'
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
