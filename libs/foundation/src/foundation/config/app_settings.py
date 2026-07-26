# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

import binascii
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from advanced_alchemy.utils.text import slugify

from foundation.__metadata__ import __version__ as current_version
from foundation.config.cache import CacheConfig
from foundation.config.compression import CompressionConfig
from foundation.config.cors import CORSConfig
from foundation.config.csrf import CSRFConfig
from foundation.config.lock import DistributedLockConfig
from foundation.config.ratelimit import RateLimitConfig
from foundation.config.wss import WebSocketConfig
from foundation.utils.env_utils import get_env
from foundation.utils.module_loader import module_to_os_path

CONFIG_PREFIX = os.environ.get('CONFIG_PREFIX', 'TAAS')
DEFAULT_MODULE_NAME = 'db'  # libs/db
# TODO: to improve since deploying in evironemtn as cloudflare workers,
# the file system is read only, we need to find a better way to handle static files in that case.
BASE_DIR: Final[Path] = module_to_os_path(DEFAULT_MODULE_NAME)
# print(f'Base directory resolved to: {BASE_DIR}')  # noqa: T201
STATIC_DIR = Path(BASE_DIR / 'server' / 'static' / 'web')

@dataclass
class AppSettings:
    """Application configuration"""

    NAME: str = field(default_factory=lambda: 'eWorkSuite')
    """Application name."""
    VERSION: str = field(default=f'v{current_version}')
    """Current application version."""
    CONTACT_NAME: str = field(default='Admin')
    """Application contact name"""
    CONTACT_EMAIL: str = field(default='admin@eworksuite.com')
    """Application contact email"""
    FRONTEND_URL: str = field(default_factory=get_env('APP_URL', 'http://localhost'))
    """The frontend base URL"""
    TENANT_PREFIX: str = field(default_factory=get_env('TENANT_PREFIX', 'taas'))
    SERVICE_NAME: str = field(default_factory=get_env(f'{CONFIG_PREFIX}_SERVICE_NAME', ''))

    DEBUG: bool = field(default_factory=get_env(f'{CONFIG_PREFIX}_DEBUG', False, bool))

    SECRET_KEY: str = field(
        default_factory=get_env(
            'SECRET_KEY', binascii.hexlify(os.urandom(32)).decode(encoding='utf-8')
        ),
    )
    OPENAPI_ENABLED: bool = field(
        default_factory=get_env('OPENAPI_ENABLED', True, bool)
    )
    """Application secret key."""
    JWT_ENCRYPTION_ALGORITHM: str = 'HS256'
    """JWT Algorithm to use"""
    ALLOWED_CORS_ORIGINS: list[str] | str = field(
        default_factory=get_env('ALLOWED_CORS_ORIGINS', ['*'], list[str])
    )
    """Allowed CORS Origins"""
    COOKIE_SECURE: bool = field(default_factory=get_env('COOKIE_SECURE', False))
    """Use secure cookies (set to True in production with HTTPS)"""
    STATIC_DIR: Path = field(default_factory=get_env('STATIC_DIR', STATIC_DIR))
    """Default URL where static assets are located."""
    STATIC_URL: str = field(default_factory=get_env('STATIC_URL', '/static/web/'))
    """URL Location for Static assets."""
    BASE_URL: str | None = None
    """Fully qualified path to optional use for URL generation."""
    DEV_MODE: bool = field(default_factory=get_env('VITE_DEV_MODE', False))
    """Toggle dev mode flag.  This can be used enable extra processes during development."""
    ENABLE_INSTRUMENTATION: bool = False
    """Enable OpenTelemetry instrumentation"""
    GOOGLE_OAUTH2_CLIENT_ID: str = field(
        default_factory=get_env('GOOGLE_OAUTH2_CLIENT_ID', '')
    )
    """Google Client ID"""
    GOOGLE_OAUTH2_CLIENT_SECRET: str = field(
        default_factory=get_env('GOOGLE_OAUTH2_CLIENT_SECRET', '')
    )
    """Google Client Secret"""
    GITHUB_OAUTH2_CLIENT_ID: str = field(
        default_factory=get_env('GITHUB_OAUTH2_CLIENT_ID', '')
    )
    """GitHub Client ID"""
    GITHUB_OAUTH2_CLIENT_SECRET: str = field(
        default_factory=get_env('GITHUB_OAUTH2_CLIENT_SECRET', '')
    )
    """GitHub Client Secret"""
    ENV_SECRETS: str = field(default_factory=get_env('ENV_SECRETS', 'runtime-secrets'))
    """Path to environment secrets."""

    CACHE_ENABLED: bool = field(default_factory=get_env('CACHE_ENABLED', True, bool))
    API_CACHE_PREFIX: str = field(
        default_factory=get_env('API_CACHE_PREFIX', 'api_cache')
    )
    CACHE_LRU_SIZE: int = 10000  # Default max size for LRU cache (number of entries)
    CACHE_EXPIRES_AFTER: int = 300  # 5 minutes

    def check_database_consistency(self) -> bool:
        """Check if database consistency check is enabled.

        Returns:
            True if database consistency check is enabled, False otherwise.
        """
        return bool(get_env(f'{CONFIG_PREFIX}_CHECK_DB_CONSISTENCY', True, bool))

    @property
    def google_oauth_enabled(self) -> bool:
        """Check if Google OAuth is configured.

        Returns:
            True if Google OAuth credentials are set.
        """
        return bool(self.GOOGLE_OAUTH2_CLIENT_ID and self.GOOGLE_OAUTH2_CLIENT_SECRET)

    @property
    def github_oauth_enabled(self) -> bool:
        """Check if GitHub OAuth is configured.

        Returns:
            True if GitHub OAuth credentials are set.
        """
        return bool(self.GITHUB_OAUTH2_CLIENT_ID and self.GITHUB_OAUTH2_CLIENT_SECRET)

    @property
    def slug(self) -> str:
        """Return a slugified name.

        Returns:
            `self.NAME`, all lowercase and hyphens instead of spaces.
        """
        return slugify(self.NAME)

    _compression_config: CompressionConfig | None = None

    def get_compression_config(self) -> CompressionConfig:
        if self._compression_config is None:
            self._compression_config = CompressionConfig(backend='gzip')
        return self._compression_config

    def get_cors_config(self) -> CORSConfig:
        return CORSConfig(allow_origins=cast('list[str]', self.ALLOWED_CORS_ORIGINS))

    def get_csrf_config(self) -> CSRFConfig:
        # TODO: implement CSRFConfig and return an instance here
        raise NotImplementedError('CSRFConfig is not implemented yet.')

    _ratelimit_config: RateLimitConfig | None = None

    def get_ratelimit_config(self) -> RateLimitConfig:
        if self._ratelimit_config is None:
            self._ratelimit_config = RateLimitConfig()
        return self._ratelimit_config

    _distributed_lock_config: DistributedLockConfig | None = None

    def get_distributed_lock_config(self) -> DistributedLockConfig:
        if self._distributed_lock_config is None:
            self._distributed_lock_config = DistributedLockConfig()
        return self._distributed_lock_config

    _cache_config: CacheConfig | None = None

    def get_cache_config(self) -> CacheConfig:
        if self._cache_config is None:
            self._cache_config = CacheConfig()
        return self._cache_config

    _websocket_config: WebSocketConfig | None = None

    def get_websocket_config(self) -> WebSocketConfig:
        if self._websocket_config is None:
            self._websocket_config = WebSocketConfig()
        return self._websocket_config

    def get_allowed_cors_origins(self) -> list[str]:
        _allowed_origins: list[str] = cast('list[str]', self.ALLOWED_CORS_ORIGINS)
        if isinstance(self.ALLOWED_CORS_ORIGINS, str):
            # Check if the string starts with "[" and ends with "]", indicating a list.
            if self.ALLOWED_CORS_ORIGINS.startswith(
                '['
            ) and self.ALLOWED_CORS_ORIGINS.endswith(']'):
                try:
                    # Safely evaluate the string as a Python list.
                    _allowed_origins = json.loads(self.ALLOWED_CORS_ORIGINS)  # pyright: ignore[reportConstantRedefinition]
                except SyntaxError, ValueError:
                    # Handle potential errors if the string is not a valid Python literal.
                    msg = 'ALLOWED_CORS_ORIGINS is not a valid list representation.'
                    raise ValueError(msg) from None
            else:
                # Split the string by commas into a list if it is not meant to be a list representation.
                _allowed_origins = [
                    host.strip() for host in self.ALLOWED_CORS_ORIGINS.split(',')
                ]  # pyright: ignore[reportConstantRedefinition]
        return _allowed_origins

    def __post_init__(self):
        pass

