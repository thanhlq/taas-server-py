# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from platform_core.utils.env_utils import get_env
from platform_core.utils.module_loader import module_to_os_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine
    from platform_core.db.sa_config import SQLAlchemyAsyncConfig

DEFAULT_MODULE_NAME = 'db'  # libs/db
# TODO: to improve since deploying in evironemtn as cloudflare workers,
# the file system is read only, we need to find a better way to handle static files in that case.
BASE_DIR: Final[Path] = module_to_os_path(DEFAULT_MODULE_NAME)


@dataclass
class KeycloakDatabaseSettings:
    """Contain pure user settings from environment variables related to database configuration."""

    ECHO: bool = field(default_factory=get_env('KEYCLOAK_DATABASE_ECHO', False))
    """Enable SQLAlchemy engine logs."""
    DEBUG: bool = field(default_factory=get_env('KEYCLOAK_DATABASE_DEBUG', False, bool))

    ECHO_POOL: bool = field(default_factory=get_env('KEYCLOAK_DATABASE_ECHO_POOL', False))
    """Enable SQLAlchemy connection pool logs."""
    POOL_DISABLED: bool = field(
        default_factory=get_env('KEYCLOAK_DATABASE_POOL_DISABLED', False, bool)
    )
    """Disable SQLAlchemy pool configuration."""
    POOL_SIZE: int = field(default_factory=get_env('KEYCLOAK_DATABASE_POOL_SIZE', 5))
    """Pool size for SQLAlchemy connection pool"""
    POOL_MAX_OVERFLOW: int = field(
        default_factory=get_env('KEYCLOAK_DATABASE_MAX_POOL_OVERFLOW', 30)
    )
    """Max overflow for SQLAlchemy connection pool"""
    POOL_TIMEOUT: int = field(default_factory=get_env('KEYCLOAK_DATABASE_POOL_TIMEOUT', 30))
    """Time in seconds for timing connections out of the connection pool."""
    POOL_RECYCLE: int = field(
        default_factory=get_env('KEYCLOAK_DATABASE_POOL_RECYCLE', default=300)
    )  # 1800: 30 minutes, 300: 5 minutes
    """
    Recycle below any LB/network idle timeout
    Amount of time to wait before recycling connections.
    """
    POOL_PRE_PING: bool = field(
        default_factory=get_env('KEYCLOAK_DATABASE_PRE_POOL_PING', False)
    )
    """
    Survive pgdog/pod restarts cleanly.
    Optionally ping database before fetching a session from the connection pool.
    """
    URL: str = field(
        default_factory=get_env(
            'KEYCLOAK_DATABASE_URL',
            'postgresql+psycopg://postgres:Pa55w0rd@localhost:15432/ews_db',
        )
    )
    """SQLAlchemy Database URL."""

    MIGRATION_ENABLED: bool = field(
        default_factory=get_env('KEYCLOAK_DATABASE_MIGRATION_ENABLED', True, bool)
    )

    _engine_instance: AsyncEngine | None = None
    """SQLAlchemy engine instance generated from settings."""

    @property
    def engine(self) -> AsyncEngine:
        return self.get_engine()

    def get_engine(self) -> AsyncEngine:
        """Get the database engine for the main database"""
        if self._engine_instance is not None:
            return self._engine_instance
        from platform_core.db.engine_factory import EngineFactory

        return EngineFactory.get_sqlalchemy_engine(self)

    def get_sqlalchemy_config(self) -> 'SQLAlchemyAsyncConfig':
        """Get SQLAlchemy configuration.

        Returns:
            The SQLAlchemy async configuration.
        """
        from platform_core.db.sa_config import (
            AlembicAsyncConfig,
            AsyncSessionConfig,
            SQLAlchemyAsyncConfig,
        )

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
