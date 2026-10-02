"""Shared fixtures for the ``resiliant`` unit tests.

These tests run against a **real** PostgreSQL database whose connection string
is read from ``.env.test`` at the repository root (``DATABASE_URL``), or from
``RESILIANT_TEST_DATABASE_URL`` when set (an isolated database: parallel runs
must not share one, the tables are truncated after every test). The
``resiliant_*`` tables are migrated at session start (``resiliant.migrations``,
the drizzle migrations shared with taas-server-js).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Awaitable, Generator
from pathlib import Path

import pytest
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment bootstrap — must happen before any `foundation`/`db` import so the
# settings modules read the test configuration.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Walk upwards until the workspace root (the dir holding ``.env.test``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env.test").exists():
            return parent
    return Path(__file__).resolve().parents[3]


load_dotenv(_repo_root() / ".env.test", override=True)
if os.environ.get("RESILIANT_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["RESILIANT_TEST_DATABASE_URL"]

# App imports must come *after* the environment has been configured.
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402


def _run_sync[T](coro: Awaitable[T]) -> T:
    """Run an awaitable on a throw-away event loop (for sync fixtures)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Tables owned by the resilience layer that the tests write to (names come from
# the models, so they follow RESILIANT_TABLE_PREFIX). Truncated between tests so
# the suite is isolated and never touches unrelated data.
from resiliant.migrations import resiliant_table_names, run_resiliant_migrations  # noqa: E402

_RESILIANT_TABLES = tuple(resiliant_table_names())


@pytest.fixture(scope="session")
def db_url() -> str:
    """Return the async database URL loaded from ``.env.test``."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set (expected from .env.test)")
    if "+psycopg" not in url and "+asyncpg" not in url:
        pytest.fail(f"DATABASE_URL must use an async driver; got: {url}")
    return url


@pytest.fixture(scope="session")
def db_engine(db_url: str) -> Generator:
    """Async engine bound to the test URL.

    ``NullPool`` keeps connections from being shared across event loops, which
    makes a session-scoped engine compatible with function-scoped async tests.
    """
    engine = create_async_engine(db_url, echo=False, poolclass=NullPool)
    _run_sync(run_resiliant_migrations(engine))
    yield engine
    _run_sync(engine.dispose())


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession]:
    """A fresh ``AsyncSession`` per test; resilience tables cleared afterward."""
    maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=db_engine, expire_on_commit=False
    )
    async with maker() as session:
        yield session

    table_list = ", ".join(f'"{t}"' for t in _RESILIANT_TABLES)
    async with db_engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
        )
