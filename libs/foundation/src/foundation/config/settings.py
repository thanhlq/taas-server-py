# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

import binascii
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Final, Optional, cast

from advanced_alchemy.utils.text import slugify
from dotenv import load_dotenv

from foundation.__metadata__ import __version__ as current_version
from foundation.cli._utils import console
from foundation.config.cache import CacheConfig
from foundation.config.compression import CompressionConfig
from foundation.config.cors import CORSConfig
from foundation.config.csrf import CSRFConfig
from foundation.config.lock import DistributedLockConfig
from foundation.config.log import LogSettings
from foundation.config.messaging_settings import MessagingSettings
from foundation.config.otel import OtelSettings
from foundation.config.ratelimit import RateLimitConfig
from foundation.config.tracing import TracingSettings
from foundation.config.wss import WebSocketConfig
from foundation.db.sa_config import (
    SQLAlchemyAsyncConfig,
)
from foundation.utils.env_utils import get_env
from foundation.utils.module_loader import module_to_os_path

from .db_settings import DatabaseSettings
from .email_settings import EmailSettings

CONFIG_PREFIX = 'TAAS'

DEFAULT_MODULE_NAME = 'db'  # libs/db
# TODO: to improve since deploying in evironemtn as cloudflare workers,
# the file system is read only, we need to find a better way to handle static files in that case.
BASE_DIR: Final[Path] = module_to_os_path(DEFAULT_MODULE_NAME)
# print(f'Base directory resolved to: {BASE_DIR}')  # noqa: T201
STATIC_DIR = Path(BASE_DIR / 'server' / 'static' / 'web')


@dataclass
class ServerSettings:
    """Server configurations."""

    APP_LOC: str = 'dma.asgi:create_app'

    """Path to app executable or factory."""
    HOST: str = field(default_factory=get_env(f'{CONFIG_PREFIX}_HOST', '0.0.0.0'))  # noqa: S104
    """Server network host."""
    PORT: int = field(default_factory=get_env(f'{CONFIG_PREFIX}_PORT', 8000))
    """Server port."""
    KEEPALIVE: int = field(default_factory=get_env(f'{CONFIG_PREFIX}_KEEPALIVE', 65))
    """Seconds to hold connections open (65 is > AWS lb idle timeout)."""
    RELOAD: bool = field(default_factory=get_env(f'{CONFIG_PREFIX}_RELOAD', False))
    """Turn on hot reloading."""
    RELOAD_DIRS: list[str] = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_RELOAD_DIRS', [f'{BASE_DIR}'])
    )
    WORKERS: int = field(default_factory=get_env(f'{CONFIG_PREFIX}_WORKERS', 1))
    """Number of worker processes."""


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
    URL: str = field(default_factory=get_env('APP_URL', 'http://localhost:8191'))
    """The frontend base URL"""

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



@dataclass
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    # saq: SaqSettings = field(default_factory=SaqSettings)
    log: LogSettings = field(default_factory=LogSettings)
    trace: TracingSettings = field(default_factory=TracingSettings)
    alchemy: SQLAlchemyAsyncConfig = field(default_factory=SQLAlchemyAsyncConfig)
    otel: OtelSettings = field(default_factory=OtelSettings)
    email: EmailSettings = field(default_factory=EmailSettings)
    messaging: MessagingSettings = field(default_factory=MessagingSettings)

    environment: str = field(default_factory=get_env('ENVIRONMENT', 'local'))
    """The current environment (development, staging, production)."""

    def is_debug(self) -> bool:
        """Check if the application is in debug mode.

        Returns:
            True if in debug mode, False otherwise.
        """
        return self.log.LOG_LEVEL == logging.DEBUG

    def find_env_file(self, filename: str) -> Path | None:
        """Search for the specified .env file in the current and parent directories.

        Args:
            filename: The name of the .env file to search for.

        Returns:
            The path to the .env file if found, otherwise None.
        """
        current_dir = Path.cwd()
        while True:
            potential_env_file = current_dir / filename
            if potential_env_file.is_file():
                return potential_env_file
            if current_dir.parent == current_dir:
                break  # Reached the root directory
            current_dir = current_dir.parent
        return None

    def _find_app_home_path(self, default_path: Optional[str] = None) -> str:
        if default_path:
            _home_path = default_path
        else:
            _home_path = os.environ.get(f'{CONFIG_PREFIX}_HOME_PATH', None)
            if _home_path:
                return _home_path
            _home_path = str(Path(os.curdir).resolve())

        if os.environ.get(f'{CONFIG_PREFIX}_HOME_PATH', None) is None:
            os.environ[f'{CONFIG_PREFIX}_HOME_PATH'] = _home_path
        return _home_path

    @classmethod
    @lru_cache(maxsize=1, typed=True)
    def from_env(
        cls, dotenv_filename: str = '.env', home_path: Optional[str] = None
    ) -> Settings:
        _app_home_path = cls()._find_app_home_path(home_path)

        logger = logging.getLogger()
        _secret_id = os.environ.get(
            'ENV_SECRETS', None
        )  # use this to load secrets in a container
        env_file = Path(f'{_app_home_path}/{dotenv_filename}')
        env_file_exists = env_file.is_file()
        if env_file_exists:
            console.print(
                f'[blue]Loading environment configuration from {dotenv_filename}[/]'
            )
            load_dotenv(
                env_file, override=False
            )  # Env vars take precedence over .env file
        else:
            console.print(
                f'[yellow]{env_file} not found. Skipping loading environment variables from file.[/]'
            )
        try:
            db: DatabaseSettings = DatabaseSettings()
            server: ServerSettings = ServerSettings()
            # saq: SaqSettings = SaqSettings()
            # vite: ViteSettings = ViteSettings()
            app: AppSettings = AppSettings()
            log: LogSettings = LogSettings()
            trace: TracingSettings = TracingSettings()
            otel: OtelSettings = OtelSettings()
            email: EmailSettings = EmailSettings()
            messaging: MessagingSettings = MessagingSettings()
        except Exception as e:  # noqa: BLE001
            logger.fatal('Could not load settings. %s', e)
            sys.exit(1)
        return Settings(
            app=app, db=db, server=server, log=log, trace=trace, otel=otel, email=email, messaging=messaging
        )


def get_settings(
    *, env_file: str = '.env', home_path: Optional[str] = None
) -> Settings:
    return Settings.from_env(env_file, home_path)


def provide_app_settings() -> AppSettings:
    """Return application settings for dependency injection.

    Returns:
        The application settings instance.
    """
    return get_settings().app
