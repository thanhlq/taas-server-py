# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from foundation.cli._cli import console
from foundation.config import AppSettings
from foundation.app.app_settings import BASE_DIR, CONFIG_PREFIX
from foundation.config.log import LogSettings
from foundation.config.messaging_settings import MessagingSettings
from foundation.config.otel import OtelSettings
from foundation.config.tracing import TracingSettings
from foundation.db.sa_config import (
    SQLAlchemyAsyncConfig,
)
from foundation.utils.env_utils import get_env

from ..email.email_settings import EmailSettings
from .db_settings import DatabaseSettings


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
            app=app,
            db=db,
            server=server,
            log=log,
            trace=trace,
            otel=otel,
            email=email,
            messaging=messaging,
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
