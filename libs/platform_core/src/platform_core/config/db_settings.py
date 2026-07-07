# .venv/lib/python3.13/site-packages/litestar_email/message.py

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from platform_core.cli import cli
from platform_core.utils.env_utils import UnsetType, get_env
from platform_core.utils.module_loader import module_to_os_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from platform_core.db.sa_config import SQLAlchemyAsyncConfig

DEFAULT_MODULE_NAME = 'db'  # libs/db
# TODO: to improve since deploying in evironemtn as cloudflare workers,
# the file system is read only, we need to find a better way to handle static files in that case.
BASE_DIR: Final[Path] = module_to_os_path(DEFAULT_MODULE_NAME)
cli.info_formal('BASE_DIR', (str(BASE_DIR)))


_UNSET = UnsetType()


def _env_field(env_key: str, default: Any, type_hint: type | UnsetType = _UNSET) -> Any:
    """Declare a setting backed by the ``env_key`` environment variable.

    With no ``prefix`` the unprefixed ``env_key`` is read (preserving the
    historical behaviour). When :class:`DatabaseSettings` is built with a
    ``prefix``, the value is re-resolved from ``f'{prefix}{env_key}'`` in
    ``__post_init__`` — the env key, default and type hint are kept in the
    field metadata so the same parsing rules apply.
    """
    return field(
        default_factory=get_env(env_key, default, type_hint),
        metadata={'env_key': env_key, 'default': default, 'type_hint': type_hint},
    )


@dataclass
class DatabaseSettings:
    """Contain pure user settings from environment variables related to database configuration.

    The set of variables read is selected by ``prefix``::

        DatabaseSettings()                  # main/default db  -> DATABASE_*
        DatabaseSettings(prefix='KEYCLOAK_')  # keycloak db    -> KEYCLOAK_DATABASE_*
        DatabaseSettings(prefix='CRM_')       # crm db         -> CRM_DATABASE_*
    """

    prefix: str = ''
    """Environment-variable prefix selecting which database to load.

    Empty (default) reads the unprefixed ``DATABASE_*`` variables; any other
    value reads ``f'{prefix}DATABASE_*'`` (e.g. ``KEYCLOAK_DATABASE_URL``).
    """

    ECHO: bool = _env_field('DATABASE_ECHO', False)
    """Enable SQLAlchemy engine logs."""
    DEBUG: bool = _env_field('DATABASE_DEBUG', False, bool)

    ECHO_POOL: bool = _env_field('DATABASE_ECHO_POOL', False)
    """Enable SQLAlchemy connection pool logs."""
    POOL_DISABLED: bool = _env_field('DATABASE_POOL_DISABLED', False, bool)
    """Disable SQLAlchemy pool configuration."""
    POOL_SIZE: int = _env_field('DATABASE_POOL_SIZE', 5)
    """Pool size for SQLAlchemy connection pool"""
    POOL_MAX_OVERFLOW: int = _env_field('DATABASE_MAX_POOL_OVERFLOW', 30)
    """Max overflow for SQLAlchemy connection pool"""
    POOL_TIMEOUT: int = _env_field('DATABASE_POOL_TIMEOUT', 30)
    """Time in seconds for timing connections out of the connection pool."""
    POOL_RECYCLE: int = _env_field('DATABASE_POOL_RECYCLE', 300)
    # 1800: 30 minutes, 300: 5 minutes
    """
    Recycle below any LB/network idle timeout
    Amount of time to wait before recycling connections.
    """
    POOL_PRE_PING: bool = _env_field('DATABASE_PRE_POOL_PING', False)
    """
    Survive pgdog/pod restarts cleanly.
    Optionally ping database before fetching a session from the connection pool.
    """
    URL: str = _env_field(
        'DATABASE_URL',
        'postgresql+psycopg://postgres:Pa55w0rd@localhost:15432/ews_db',
    )
    """SQLAlchemy Database URL."""

    MIGRATION_ENABLED: bool = _env_field('DATABASE_MIGRATION_ENABLED', True, bool)

    MIGRATION_CONFIG: str = _env_field(
        'DATABASE_MIGRATION_CONFIG', f'{BASE_DIR}/db/migrations/alembic.ini'
    )
    """The path to the `alembic.ini` configuration file."""
    MIGRATION_PATH: str = _env_field(
        'DATABASE_MIGRATION_PATH', f'{BASE_DIR}/db/migrations'
    )
    """The path to the `alembic` database migrations."""
    MIGRATION_DDL_VERSION_TABLE: str = _env_field(
        'DATABASE_MIGRATION_DDL_VERSION_TABLE', 'ddl_version'
    )
    """The name to use for the `alembic` versions table name."""
    FIXTURE_PATH: str = _env_field('DATABASE_FIXTURE_PATH', f'{BASE_DIR}/db/fixtures')
    """The path to JSON fixture files to load into tables."""
    _engine_instance: AsyncEngine | None = None
    """SQLAlchemy engine instance generated from settings."""

    def __post_init__(self) -> None:
        """Re-resolve every env-backed field under ``prefix`` when one is set.

        The ``default_factory`` of each field has already loaded the
        unprefixed value; for a non-empty prefix we re-read the same key with
        the prefix prepended, keeping each field's default and type hint.
        """
        if not self.prefix:
            return
        for f in fields(self):
            env_key = f.metadata.get('env_key')
            if env_key is None:
                continue
            setattr(
                self,
                f.name,
                get_env(
                    f'{self.prefix}{env_key}',
                    f.metadata['default'],
                    f.metadata['type_hint'],
                )(),
            )

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
