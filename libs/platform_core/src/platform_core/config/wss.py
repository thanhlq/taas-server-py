from __future__ import annotations

from dataclasses import dataclass, field

from platform_core.utils.env_utils import get_env

__all__ = ('WebSocketConfig',)


CONFIG_PREFIX = 'TAAS'


@dataclass
class WebSocketConfig:
    """Configuration for WebSocket / Socket.IO pub-sub.

    Mirrors the ``WEBSOCKET_*`` fields previously defined inline on
    :class:`AppSettings`. The Redis backend is used as the pub-sub fan-out
    layer so multiple server instances can share rooms and broadcast events
    — same env vars work across frameworks.
    """

    enabled: bool = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_WEBSOCKET_ENABLED', True)
    )
    """Master switch. When False, adapters skip installing the pub-sub
    backend (single-process Socket.IO still works locally)."""

    provider: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_WEBSOCKET_PROVIDER', 'redis')
    )
    """Pub-sub backend: ``redis`` (multi-process fan-out) or ``memory``
    (single-process; only safe for dev / tests)."""

    # ---- Redis backend ------------------------------------------------------
    redis_host: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_REDIS_HOST', 'redis://redis:6379/0'
        )
    )
    """Redis URL or sentinel host list. For single-node use
    ``redis://host:port/db``; for sentinel pass a comma-separated host:port
    list and set :attr:`redis_master_name`."""

    redis_password: str = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_WEBSOCKET_REDIS_PASSWORD', '')
    )
    """Empty string = no auth."""

    redis_master_name: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_REDIS_MASTER_NAME', 'pubsub-master'
        )
    )
    """Redis Sentinel master name. Ignored when :attr:`redis_host` is a plain
    ``redis://`` URL."""

    # ---- Socket.IO behaviour ------------------------------------------------
    socketio_path: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_SOCKETIO_PATH', 'socket.io'
        )
    )
    """URL path where the Socket.IO server is mounted. Clients connect to
    ``ws://host/<socketio_path>/``. Must match the client's ``path`` option."""

    channel_prefix: str = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_CHANNEL_PREFIX', 'wss'
        )
    )
    """Prefix for pub-sub channel names — lets you share one Redis with
    other apps without collisions."""

    ping_interval: int = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_PING_INTERVAL', 25, int
        )
    )
    """Server-initiated heartbeat interval, in seconds. Clients that miss
    a heartbeat are considered disconnected. Matches Socket.IO's default."""

    ping_timeout: int = field(
        default_factory=get_env(
            f'{CONFIG_PREFIX}_WEBSOCKET_PING_TIMEOUT', 20, int
        )
    )
    """How long to wait for a pong before declaring the client gone, in
    seconds. Must be < :attr:`ping_interval` for reliable detection."""
