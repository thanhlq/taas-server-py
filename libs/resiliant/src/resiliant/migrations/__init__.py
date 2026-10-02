"""
Migrations of the ``resiliant_*`` tables — shared with taas-server-js.

The DDL has ONE source: the drizzle migrations of ``@taas/resiliant``
(``taas-server-js/packages/resiliant/drizzle``), vendored here byte for byte in
``drizzle/`` (``tests/unit_local/test_migrations_parity.py`` fails when the copies
drift; ``scripts/sync-resiliant-migrations.sh`` refreshes them).

:func:`run_resiliant_migrations` speaks drizzle's protocol exactly — same history
table (``drizzle.__resiliant_migrations``), same sha256 hashes, same
``folderMillis`` ordering — so the Node services and the Python migrator can both
run it against the same database, in any order, idempotently.
"""

from .runner import (
    RESILIANT_MIGRATIONS_FOLDER,
    RESILIANT_MIGRATIONS_SCHEMA,
    RESILIANT_MIGRATIONS_TABLE,
    Migration,
    applied_migrations,
    drop_resiliant_tables,
    read_migrations,
    resiliant_table_names,
    run_resiliant_migrations,
)

__all__ = [
    'Migration',
    'RESILIANT_MIGRATIONS_FOLDER',
    'RESILIANT_MIGRATIONS_SCHEMA',
    'RESILIANT_MIGRATIONS_TABLE',
    'applied_migrations',
    'drop_resiliant_tables',
    'read_migrations',
    'resiliant_table_names',
    'run_resiliant_migrations',
]
