"""Database wiring for the ``unit`` test layer (CI / release).

Provides the ``db_url`` fixture by spinning up a disposable PostgreSQL
*testcontainer*. This requires Docker to be available but needs no local
database setup, which makes it the right choice for CI and release pipelines.

All other fixtures (engine, schema, session, services, factories) are inherited
from the shared ``tests/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def db_url() -> Generator[str, None, None]:
    """Start a throw-away Postgres container and yield its async URL.

    The ``psycopg`` (v3) driver is requested so the URL works directly with
    SQLAlchemy's async engine.
    """
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        yield postgres.get_connection_url()
