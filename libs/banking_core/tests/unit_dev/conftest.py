"""Database wiring for the ``unit_dev`` test layer (local development).

Provides the ``db_url`` fixture by reading ``DATABASE_URL`` from the
environment, which the shared ``tests/conftest.py`` has already populated from
``.env.test``. This points the suite at the developer's *local* database, so it
runs fast and needs no Docker — at the cost of requiring a reachable Postgres
instance. Use it for the inner-loop, development-only runs.

All other fixtures (engine, schema, session, services, factories) are inherited
from the shared ``tests/conftest.py``.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def db_url() -> str:
    """Return the local async database URL loaded from ``.env.test``."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set (expected from .env.test)")
    if "+psycopg" not in url and "+asyncpg" not in url:
        pytest.fail(
            f"DATABASE_URL must use an async driver (e.g. +psycopg_async); got: {url}"
        )
    return url
