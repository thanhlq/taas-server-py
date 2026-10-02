"""Drizzle-compatible migration runner (see ``drizzle-orm`` ``readMigrationFiles`` + ``PgDialect.migrate``)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

RESILIANT_MIGRATIONS_FOLDER = Path(__file__).resolve().parent / 'drizzle'
RESILIANT_MIGRATIONS_SCHEMA = 'drizzle'
RESILIANT_MIGRATIONS_TABLE = '__resiliant_migrations'
_BREAKPOINT = '--> statement-breakpoint'

logger = logging.getLogger('resiliant.migrations')


@dataclass(frozen=True, slots=True)
class Migration:
    tag: str
    folder_millis: int
    hash: str
    statements: tuple[str, ...]


def read_migrations(folder: Path = RESILIANT_MIGRATIONS_FOLDER) -> list[Migration]:
    """The journal's migrations, hashed and split exactly like drizzle does."""
    journal = json.loads((folder / 'meta' / '_journal.json').read_text())
    migrations: list[Migration] = []
    for entry in journal['entries']:
        # Bytes, not text: the hash must equal Node's sha256 of the same file.
        raw = (folder / f'{entry["tag"]}.sql').read_bytes()
        query = raw.decode('utf-8')
        migrations.append(
            Migration(
                tag=entry['tag'],
                folder_millis=int(entry['when']),
                hash=hashlib.sha256(raw).hexdigest(),
                statements=tuple(query.split(_BREAKPOINT)),
            )
        )
    return migrations


def _history() -> str:
    return f'"{RESILIANT_MIGRATIONS_SCHEMA}"."{RESILIANT_MIGRATIONS_TABLE}"'


async def _ensure_history(conn: AsyncConnection) -> None:
    await conn.execute(
        text(f'CREATE SCHEMA IF NOT EXISTS "{RESILIANT_MIGRATIONS_SCHEMA}"')
    )
    await conn.execute(
        text(
            f'CREATE TABLE IF NOT EXISTS {_history()} (id SERIAL PRIMARY KEY, hash text NOT NULL, created_at bigint)'
        )
    )


async def applied_migrations(engine: AsyncEngine) -> list[tuple[str, int]]:
    """``(hash, created_at)`` rows of the history table, oldest first (empty when never migrated)."""
    async with engine.connect() as conn:
        exists = (
            await conn.execute(
                text('select to_regclass(:name)'),
                {'name': f'{RESILIANT_MIGRATIONS_SCHEMA}.{RESILIANT_MIGRATIONS_TABLE}'},
            )
        ).scalar()
        if not exists:
            return []
        rows = await conn.execute(
            text(f'select hash, created_at from {_history()} order by created_at')
        )
        return [(row.hash, int(row.created_at)) for row in rows]


async def run_resiliant_migrations(
    engine: AsyncEngine, folder: Path = RESILIANT_MIGRATIONS_FOLDER
) -> list[str]:
    """Apply the migrations newer than the last recorded one (all in one transaction).

    Returns the tags applied (empty = already up to date).
    """
    migrations = read_migrations(folder)
    async with engine.begin() as conn:
        await _ensure_history(conn)
        # Serialise concurrent migrators (several services starting at once).
        await conn.execute(
            text("select pg_advisory_xact_lock(hashtext('resiliant_migrations'))")
        )
        last = (
            await conn.execute(
                text(
                    f'select created_at from {_history()} order by created_at desc limit 1'
                )
            )
        ).scalar()
        applied: list[str] = []
        for migration in migrations:
            if last is not None and int(last) >= migration.folder_millis:
                continue
            for statement in migration.statements:
                if statement.strip():
                    await conn.exec_driver_sql(statement)
            await conn.execute(
                text(
                    f'insert into {_history()} ("hash", "created_at") values (:hash, :created_at)'
                ),
                {'hash': migration.hash, 'created_at': migration.folder_millis},
            )
            applied.append(migration.tag)
    if applied:
        logger.info('resiliant migrations applied: %s', ', '.join(applied))
    return applied


def resiliant_table_names() -> list[str]:
    """Tables the shipped migrations create (the ORM models of ``resiliant.models``)."""
    from resiliant.models import (
        DLQEventArchiveTable,
        DLQEventTable,
        MessagingOutboxTable,
        ProcessedEventTable,
        SagaStateTable,
        ScheduledJobTable,
        TransactionOutboxTable,
    )

    return [
        model.__tablename__
        for model in (
            DLQEventTable,
            DLQEventArchiveTable,
            MessagingOutboxTable,
            TransactionOutboxTable,
            ProcessedEventTable,
            SagaStateTable,
            ScheduledJobTable,
        )
    ]


async def drop_resiliant_tables(engine: AsyncEngine) -> None:
    """Drop the resiliant tables and their history. Development / tests only."""
    tables = ', '.join(f'"{name}"' for name in resiliant_table_names())
    async with engine.begin() as conn:
        await conn.execute(text(f'drop table if exists {tables} cascade'))
        await conn.execute(text(f'drop table if exists {_history()}'))
