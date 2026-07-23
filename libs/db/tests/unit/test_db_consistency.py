"""Database consistency test — Alembic edition.

Purpose
-------
Verify the database schema produced by the **migrations** matches the schema
declared by the ORM models. The shared test fixtures normally build the schema
straight from the models (``metadata.create_all``), which makes any such check
trivially pass — so this test instead builds the schema from the real
migrations and only then compares it against the models.

How it works (fully self-contained, only Docker required)
---------------------------------------------------------
1. Start a throwaway Postgres testcontainer.
2. Apply the Alembic migrations to it with the project's own runner::

       DATABASE_URL=<container> python -m db.migrations upgrade head

   This is the exact production migration path (see
   ``libs/db/src/db/migrations/migration-guide.md``). It is run *out of
   process* because the runner calls ``asyncio.run()`` internally, which cannot
   be nested inside pytest's event loop. ``DATABASE_URL`` is honoured over the
   repo ``.env`` because ``foundation`` loads dotenv with ``override=False``.
3. Run the consistency check against the migrated schema and assert it is clean.

Ported from the original Liquibase-based test; the only conceptual change is the
migration engine (Liquibase → Alembic), so no ``-Dprefix`` / changelog wiring is
needed — the models bake no dynamic table prefix.

Run it::

    uv run pytest libs/db/tests/unit/test_db_consistency.py -v -s
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest


def _repo_root() -> Path:
    """Walk up to the workspace root (the dir that holds ``libs/db``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / 'libs' / 'db' / 'src' / 'db' / 'migrations').is_dir():
            return parent
    raise RuntimeError('Could not locate the taas-server-py workspace root')


def _run_alembic_upgrade(database_url: str) -> None:
    """Apply all Alembic migrations to ``database_url`` via the project runner.

    Runs ``python -m db.migrations upgrade head`` out-of-process with
    ``DATABASE_URL`` overridden to point at the testcontainer. The runner reads
    the URL from ``Settings.db.URL``; the repo ``.env`` cannot shadow our value
    because dotenv is loaded with ``override=False``.
    """
    env = dict(os.environ)
    env['DATABASE_URL'] = database_url

    result = subprocess.run(
        [sys.executable, '-m', 'db.migrations', 'upgrade', 'head'],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f'Alembic migration failed (exit code {result.returncode}).\n'
            f'--- stdout ---\n{result.stdout}\n'
            f'--- stderr ---\n{result.stderr}'
        )


async def test_database_consistency_check() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from testcontainers.postgres import PostgresContainer

    # Import the models package so every model registers on the shared
    # advanced-alchemy registry before we enumerate/inspect it.
    import db.models  # noqa: F401
    from db.models.base import AdvancedDeclarativeBase
    from db.utils.db_consistency_check import a_run_database_consistency_check

    # ``driver='psycopg'`` (v3) gives an async-ready URL that works both with
    # ``create_async_engine`` here and with the migration runner's engine.
    with PostgresContainer('postgres:16-alpine', driver='psycopg') as postgres:
        database_url = postgres.get_connection_url()

        # 1) Build the schema from the migrations (NOT from the ORM models).
        _run_alembic_upgrade(database_url)

        # 2) Run the consistency check against the migrated schema.
        engine = create_async_engine(
            database_url,
            poolclass=NullPool,
            connect_args={'prepare_threshold': None},
        )
        try:
            model_count = len(list(AdvancedDeclarativeBase.registry.mappers))
            print(
                f'\n🐘 Validating {model_count} models against the '
                'Alembic-migrated schema...'
            )
            errors: List[str] = await a_run_database_consistency_check(
                AdvancedDeclarativeBase, engine
            )
        finally:
            await engine.dispose()

    assert not errors, (
        f'Database consistency check failed with {len(errors)} error(s):\n'
        + '\n'.join(errors)
    )
