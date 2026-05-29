"""Alembic migration runner for libs/db.

Usage:
    uv run python -m db.migrations <command> [args]

Commands:
    current                       Show the current revision in the DB
    history                       Show revision history
    revision -m "<msg>"           Create an empty revision
    revision --autogenerate -m "<msg>"
                                  Create a revision diffing models vs DB
    upgrade [revision]            Upgrade to revision (default: head)
    downgrade <revision>          Downgrade to revision (-1 for one step back)
    stamp <revision>              Mark the DB as being at <revision> without
                                  running migrations (use after manual fixes)

Reads the DB URL from ``Settings.db.URL`` (via platform_core.config), which in
turn reads ``DATABASE_URL`` from the project's .env. Override per-invocation
with ``DATABASE_URL=... uv run python -m db.migrations ...``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from advanced_alchemy.alembic.commands import AlembicCommandConfig
from alembic import command as alembic_command
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from platform_core.config import get_settings


_HERE = Path(__file__).resolve().parent
_ALEMBIC_INI = _HERE / 'alembic.ini'


def _to_async_url(url: str) -> str:
    """Ensure the URL uses an async driver.

    SQLAlchemy's ``create_async_engine`` requires the dialect+driver to be
    async. ``postgresql://`` (no driver) defaults to a sync driver and breaks
    advanced-alchemy's async migration path. Normalise to ``postgresql+psycopg``
    (psycopg3 supports both sync and async via the same dialect name).
    """
    u = make_url(url)
    if u.drivername == 'postgresql':
        u = u.set(drivername='postgresql+psycopg')
    return u.render_as_string(hide_password=False)


def _build_config() -> AlembicCommandConfig:
    settings = get_settings()
    db_url = _to_async_url(settings.db.URL)
    version_table = settings.db.MIGRATION_DDL_VERSION_TABLE

    engine = create_async_engine(db_url, future=True)

    return AlembicCommandConfig(
        engine=engine,
        version_table_name=version_table,
        file_=str(_ALEMBIC_INI),
        compare_type=True,  # detect column type changes in autogenerate
    )


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m db.migrations',
        description='Alembic migrations for libs/db',
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('current', help='Show current DB revision')
    sub.add_parser('history', help='Show revision history')

    p_rev = sub.add_parser('revision', help='Create a new revision')
    p_rev.add_argument('-m', '--message', required=True, help='Revision message')
    p_rev.add_argument(
        '--autogenerate', action='store_true',
        help='Diff models against DB to populate the revision',
    )

    p_up = sub.add_parser('upgrade', help='Apply migrations forward')
    p_up.add_argument('revision', nargs='?', default='head')
    p_up.add_argument('--sql', action='store_true', help='Emit SQL, do not run')

    p_down = sub.add_parser('downgrade', help='Roll migrations back')
    p_down.add_argument('revision')
    p_down.add_argument('--sql', action='store_true', help='Emit SQL, do not run')

    p_stamp = sub.add_parser(
        'stamp', help='Mark DB at <revision> without running it',
    )
    p_stamp.add_argument('revision')

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    config = _build_config()

    if args.cmd == 'current':
        alembic_command.current(config, verbose=True)
    elif args.cmd == 'history':
        alembic_command.history(config, verbose=True)
    elif args.cmd == 'revision':
        alembic_command.revision(
            config, message=args.message, autogenerate=args.autogenerate,
        )
    elif args.cmd == 'upgrade':
        alembic_command.upgrade(config, revision=args.revision, sql=args.sql)
    elif args.cmd == 'downgrade':
        alembic_command.downgrade(config, revision=args.revision, sql=args.sql)
    elif args.cmd == 'stamp':
        alembic_command.stamp(config, revision=args.revision)
    else:
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
