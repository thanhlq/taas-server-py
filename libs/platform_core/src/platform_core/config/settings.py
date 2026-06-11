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
from typing import TYPE_CHECKING, Final, Optional, cast

from advanced_alchemy.utils.text import slugify
from dotenv import load_dotenv

from platform_core.__metadata__ import __version__ as current_version
from platform_core.cli._utils import console
from platform_core.config.cache import CacheConfig
from platform_core.config.compression import CompressionConfig
from platform_core.config.cors import CORSConfig
from platform_core.config.csrf import CSRFConfig
from platform_core.config.lock import DistributedLockConfig
from platform_core.config.ratelimit import RateLimitConfig
from platform_core.config.wss import WebSocketConfig
from platform_core.db.db_config import (
    AlembicAsyncConfig,
    AsyncSessionConfig,
    SQLAlchemyAsyncConfig,
)
from platform_core.email import EmailConfig, ResendConfig, SMTPConfig
from platform_core.utils.env_utils import get_env
from platform_core.utils.module_loader import module_to_os_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

CONFIG_PREFIX = 'TAAS'

DEFAULT_MODULE_NAME = 'db'  # libs/db
# TODO: to improve since deploying in evironemtn as cloudflare workers,
# the file system is read only, we need to find a better way to handle static files in that case.
BASE_DIR: Final[Path] = module_to_os_path(DEFAULT_MODULE_NAME)
# print(f'Base directory resolved to: {BASE_DIR}')  # noqa: T201
STATIC_DIR = Path(BASE_DIR / 'server' / 'static' / 'web')

# cli_print_info_formal('DB MIGRATIONS MODULE', str(BASE_DIR.resolve()))


@dataclass
class DatabaseSettings:
    ECHO: bool = field(default_factory=get_env('DATABASE_ECHO', False))
    """Enable SQLAlchemy engine logs."""
    DEBUG: bool = field(
        default_factory=get_env(f'{CONFIG_PREFIX}_DEBUG_DATABASE', False, bool)
    )

    ECHO_POOL: bool = field(default_factory=get_env('DATABASE_ECHO_POOL', False))
    """Enable SQLAlchemy connection pool logs."""
    POOL_DISABLED: bool = field(
        default_factory=get_env('DATABASE_POOL_DISABLED', False, bool)
    )
    """Disable SQLAlchemy pool configuration."""
    POOL_SIZE: int = field(default_factory=get_env('DATABASE_POOL_SIZE', 5))
    """Pool size for SQLAlchemy connection pool"""
    POOL_MAX_OVERFLOW: int = field(
        default_factory=get_env('DATABASE_MAX_POOL_OVERFLOW', 30)
    )
    """Max overflow for SQLAlchemy connection pool"""
    POOL_TIMEOUT: int = field(default_factory=get_env('DATABASE_POOL_TIMEOUT', 30))
    """Time in seconds for timing connections out of the connection pool."""
    POOL_RECYCLE: int = field(default_factory=get_env('DATABASE_POOL_RECYCLE', default=300)) # 1800: 30 minutes, 300: 5 minutes
    """
    Recycle below any LB/network idle timeout
    Amount of time to wait before recycling connections.
    """
    POOL_PRE_PING: bool = field(
        default_factory=get_env('DATABASE_PRE_POOL_PING', False)
    )
    """
    Survive pgdog/pod restarts cleanly.
    Optionally ping database before fetching a session from the connection pool.
    """
    URL: str = field(
        default_factory=get_env(
            'DATABASE_URL',
            'postgresql+psycopg://postgres:Pa55w0rd@localhost:15432/ews_db',
        )
    )
    """SQLAlchemy Database URL."""

    MIGRATION_ENABLED: bool = field(
        default_factory=get_env('DATABASE_MIGRATION_ENABLED', True, bool)
    )

    MIGRATION_CONFIG: str = field(
        default_factory=get_env(
            'DATABASE_MIGRATION_CONFIG', f'{BASE_DIR}/db/migrations/alembic.ini'
        )
    )
    """The path to the `alembic.ini` configuration file."""
    MIGRATION_PATH: str = field(
        default_factory=get_env('DATABASE_MIGRATION_PATH', f'{BASE_DIR}/db/migrations')
    )
    """The path to the `alembic` database migrations."""
    MIGRATION_DDL_VERSION_TABLE: str = field(
        default_factory=get_env('DATABASE_MIGRATION_DDL_VERSION_TABLE', 'ddl_version')
    )
    """The name to use for the `alembic` versions table name."""
    FIXTURE_PATH: str = field(
        default_factory=get_env('DATABASE_FIXTURE_PATH', f'{BASE_DIR}/db/fixtures')
    )
    """The path to JSON fixture files to load into tables."""
    _engine_instance: AsyncEngine | None = None
    """SQLAlchemy engine instance generated from settings."""

    @property
    def engine(self) -> AsyncEngine:
        return self.get_engine()

    def get_engine(self) -> AsyncEngine:
        if self._engine_instance is not None:
            return self._engine_instance
        from platform_core.db.engine_factory import EngineFactory

        return EngineFactory.get_sqlalchemy_engine(self)

    def get_config(self) -> SQLAlchemyAsyncConfig:
        """Get SQLAlchemy configuration.

        Returns:
            The SQLAlchemy async configuration.
        """
        return SQLAlchemyAsyncConfig(
            engine_instance=self.get_engine(),
            before_send_handler='autocommit',
            session_config=AsyncSessionConfig(expire_on_commit=False),
            alembic_config=AlembicAsyncConfig(
                version_table_name=self.MIGRATION_DDL_VERSION_TABLE,
                script_config=self.MIGRATION_CONFIG,
                script_location=self.MIGRATION_PATH,
            ),
        )


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
class EmailSettings:
    """Email configuration.

    Set EMAIL_BACKEND to:
    - "console" (default) - prints emails to stdout (development)
    - "memory" - stores in memory (testing)
    - "smtp" - sends via SMTP server
    - "resend" - sends via Resend API (production)
    """

    BACKEND: str = field(default_factory=get_env('EMAIL_BACKEND', 'console'))
    """Email backend: console, memory, smtp, resend."""
    FROM_EMAIL: str = field(
        default_factory=get_env('EMAIL_FROM_ADDRESS', 'noreply@localhost')
    )
    """Default from email address."""
    FROM_NAME: str = field(default_factory=get_env('EMAIL_FROM_NAME', 'Litestar App'))
    """Default from name."""
    # SMTP settings (only used when BACKEND="smtp")
    SMTP_HOST: str = field(default_factory=get_env('EMAIL_SMTP_HOST', 'localhost'))
    """SMTP server hostname."""
    SMTP_PORT: int = field(default_factory=get_env('EMAIL_SMTP_PORT', 587, int))
    """SMTP server port."""
    SMTP_USER: str = field(default_factory=get_env('EMAIL_SMTP_USER', ''))
    """SMTP username."""
    SMTP_PASSWORD: str = field(default_factory=get_env('EMAIL_SMTP_PASSWORD', ''))
    """SMTP password."""
    USE_TLS: bool = field(default_factory=get_env('EMAIL_USE_TLS', True))
    """Use TLS for SMTP connection."""
    USE_SSL: bool = field(default_factory=get_env('EMAIL_USE_SSL', False))
    """Use SSL for SMTP connection."""
    TIMEOUT: int = field(default_factory=get_env('EMAIL_TIMEOUT', 30, int))
    """SMTP connection timeout in seconds."""
    # Resend settings (only used when BACKEND="resend")
    RESEND_API_KEY: str = field(default_factory=get_env('RESEND_API_KEY', ''))
    """Resend API key for production email sending."""

    def get_config(self) -> EmailConfig:
        """Return EmailConfig for the litestar-email plugin.

        As of litestar-email v0.3.0, the backend parameter accepts either
        a string ("console", "memory") or a config object (SMTPConfig,
        ResendConfig).

        Returns:
            The email configuration.
        """
        backend: str | SMTPConfig | ResendConfig = self.BACKEND
        if self.BACKEND == 'smtp':
            backend = SMTPConfig(
                host=self.SMTP_HOST,
                port=self.SMTP_PORT,
                username=self.SMTP_USER,
                password=self.SMTP_PASSWORD,
                use_tls=self.USE_TLS,
                use_ssl=self.USE_SSL,
                timeout=self.TIMEOUT,
            )
        elif self.BACKEND == 'resend':
            backend = ResendConfig(api_key=self.RESEND_API_KEY)
        return EmailConfig(
            backend=backend,
            from_email=self.FROM_EMAIL,
            from_name=self.FROM_NAME,
        )


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
    API_CACHE_PREFIX: str = field(default_factory=get_env('API_CACHE_PREFIX', 'api_cache'))
    CACHE_LRU_SIZE: int = 10000 # Default max size for LRU cache (number of entries)
    CACHE_EXPIRES_AFTER: int = 300 # 5 minutes

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

    def __post_init__(self) -> None:
        # Check if the ALLOWED_CORS_ORIGINS is a string.
        if isinstance(self.ALLOWED_CORS_ORIGINS, str):
            # Check if the string starts with "[" and ends with "]", indicating a list.
            if self.ALLOWED_CORS_ORIGINS.startswith(
                '['
            ) and self.ALLOWED_CORS_ORIGINS.endswith(']'):
                try:
                    # Safely evaluate the string as a Python list.
                    self.ALLOWED_CORS_ORIGINS = json.loads(self.ALLOWED_CORS_ORIGINS)  # pyright: ignore[reportConstantRedefinition]
                except SyntaxError, ValueError:
                    # Handle potential errors if the string is not a valid Python literal.
                    msg = 'ALLOWED_CORS_ORIGINS is not a valid list representation.'
                    raise ValueError(msg) from None
            else:
                # Split the string by commas into a list if it is not meant to be a list representation.
                self.ALLOWED_CORS_ORIGINS = [
                    host.strip() for host in self.ALLOWED_CORS_ORIGINS.split(',')
                ]  # pyright: ignore[reportConstantRedefinition]


@dataclass
class LogSettings:
    """Logger configuration"""

    # https://stackoverflow.com/a/1845097/6560549
    EXCLUDE_PATHS: str = r'\A(?!x)x'
    """Regex to exclude paths from logging."""
    INCLUDE_COMPRESSED_BODY: bool = False
    """Include 'body' of compressed responses in log output."""
    LEVEL: int = field(default_factory=get_env('LOG_LEVEL', 30))
    """Stdlib log levels.

    Only emit logs at this level, or higher.
    """
    OBFUSCATE_COOKIES: set[str] = field(
        default_factory=lambda: {'session', 'XSRF-TOKEN'}
    )
    """Request cookie keys to obfuscate."""
    OBFUSCATE_HEADERS: set[str] = field(
        default_factory=lambda: {'Authorization', 'X-API-KEY', 'X-XSRF-TOKEN'}
    )
    """Attributes of the [Response][litestar.response.Response] to be
    logged."""
    SAQ_LEVEL: int = field(default_factory=get_env('SAQ_LOG_LEVEL', 50))
    """Level to log SAQ logs."""
    SQLALCHEMY_LEVEL: int = field(default_factory=get_env('SQLALCHEMY_LOG_LEVEL', 30))
    """Level to log SQLAlchemy logs."""
    ASGI_ACCESS_LEVEL: int = field(default_factory=get_env('ASGI_ACCESS_LOG_LEVEL', 30))
    """Level to log uvicorn access logs."""
    ASGI_ERROR_LEVEL: int = field(default_factory=get_env('ASGI_ERROR_LOG_LEVEL', 30))
    """Level to log uvicorn error logs."""


@dataclass
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    db: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    # saq: SaqSettings = field(default_factory=SaqSettings)
    log: LogSettings = field(default_factory=LogSettings)
    alchemy: SQLAlchemyAsyncConfig = field(default_factory=SQLAlchemyAsyncConfig)
    email: EmailSettings = field(default_factory=EmailSettings)

    environment: str = field(default_factory=get_env('ENVIRONMENT', 'local'))
    """The current environment (development, staging, production)."""

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
            return default_path

        _home_path = os.environ.get(f'{CONFIG_PREFIX}_HOME_PATH', None)
        if _home_path:
            return _home_path

        # print(f'Current working directory (Path.cwd()): {Path.cwd()}')  # noqa: T201
        # print(f'Current working directory (os.curdir): {os.curdir} / {Path(os.curdir).resolve()}')  # noqa: T201

        _home_path = str(Path(os.curdir).resolve())

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
        except Exception as e:  # noqa: BLE001
            logger.fatal('Could not load settings. %s', e)
            sys.exit(1)
        return Settings(app=app, db=db, server=server, log=log)


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
