"""Local infra for the blob_service unit_dev layer: RustFS (localhost:19000, app / app) + local Postgres.

`DATABASE_URL` comes from `taas-server-py/.env.test` (else `.env`); only local hosts are accepted.
Tests skip when RustFS or the database is unreachable.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

RUSTFS_ENDPOINT = os.getenv('BLOB_TEST_RUSTFS_ENDPOINT', 'http://localhost:19000')
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


def _server_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / 'pyproject.toml').exists() and (parent / 'libs').is_dir():
            return parent
    return Path(__file__).resolve().parents[4]


def _database_url() -> str | None:
    if url := os.getenv('BLOB_TEST_DATABASE_URL'):
        return url
    root = _server_root()
    for name in ('.env.test', '.env'):
        path = root / name
        if path.exists() and (url := dotenv_values(path).get('DATABASE_URL')):
            return url
    return os.getenv('DATABASE_URL')


def _rustfs_reachable() -> bool:
    try:
        return httpx.get(f'{RUSTFS_ENDPOINT}/health', timeout=2).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.fixture(scope='session')
def rustfs_endpoint() -> str:
    if not _rustfs_reachable():
        pytest.skip(f'RustFS not reachable on {RUSTFS_ENDPOINT}')
    return RUSTFS_ENDPOINT


@pytest.fixture(scope='session')
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip('DATABASE_URL is not set (expected in .env.test or .env)')
    parsed = make_url(url)
    if parsed.host not in LOCAL_HOSTS:
        pytest.skip(f'refusing to run against a non-local database host: {parsed.host}')
    if '+psycopg' not in url and '+asyncpg' not in url:
        pytest.fail(
            f'DATABASE_URL must use an async driver; got: {parsed.render_as_string(hide_password=True)}'
        )
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1 FROM taas_tenants LIMIT 1'))
    except Exception as e:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f'local database not usable: {e}')
    yield engine
    await engine.dispose()
