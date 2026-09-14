"""
Outbox partition maintenance.

Wraps the two PL/pgSQL functions shipped with the ``message_outbox`` migration
(``81_message_outbox.yml``) so they can be driven from application code:

  - ``{prefix}_create_message_outbox_partitions(weeks_ahead)`` — idempotently
    creates the upcoming weekly partitions (skips any that already exist).
  - ``{prefix}_drop_old_message_outbox_partitions(retention_weeks)`` — drops
    weekly partitions older than the retention window.

The outbox table lives in the *main* application database, so this maintainer
talks to ``core.db.db_manager``. The tenant prefix is supplied by the caller
(which already holds a settings instance), so this class does not load settings
itself and can be instantiated once and reused.

Not every deployment ships the partitioned outbox: the libs/db baseline
migration creates ``resiliant_outbox_events`` as a plain table and defines no
partition functions at all. :meth:`OutboxPartitionMaintainer.is_available`
probes the database for the functions so callers can skip maintenance
gracefully instead of failing the scheduled job on every run.

Intended to be driven by a single ``@faust_app.timer(on_leader=True)``, so no
cross-process locking is needed here.
"""

from __future__ import annotations
from foundation.db.advanced_db_manager import MainDatabase, AdvancedDBManager
from foundation.observability.log_factory import LogFactory

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text


CREATE_PARTITIONS_FN = "create_message_outbox_partitions"
DROP_PARTITIONS_FN = "drop_old_message_outbox_partitions"


@dataclass
class OutboxMaintenanceResult:
    """Outcome of a single outbox maintenance pass."""

    created: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)


class OutboxPartitionMaintainer:
    """Creates upcoming and prunes expired ``message_outbox`` partitions."""

    def __init__(
        self, prefix: str, db_manager: Optional[AdvancedDBManager] = None
    ) -> None:
        self._prefix = prefix
        self._db = db_manager if db_manager is not None else MainDatabase.get_instance()
        self._logger = LogFactory().get_logger('Outbox Partition Maintenance')

    def qualified_name(self, function: str) -> str:
        """Return ``function`` qualified with the tenant prefix.

        Follows the same convention as the prefixed tables (``taas_…``): a bare
        prefix such as ``taas`` gets an underscore separator, while a prefix that
        already ends in ``_`` (``taas_``) or is a schema qualifier (``taas.``)
        is used verbatim. An empty prefix yields the bare function name.
        """
        prefix = self._prefix or ""
        if prefix and not prefix.endswith(("_", ".")):
            prefix = f"{prefix}_"
        return f"{prefix}{function}"

    async def is_available(self, conn=None) -> bool:
        """Return ``True`` when the partition-maintenance functions exist.

        Uses ``to_regproc`` so the probe never raises for a missing function.
        Pass an open connection to reuse it; otherwise one is opened.
        """
        if conn is not None:
            return await self._probe(conn)
        async with self._db.connect() as opened:
            return await self._probe(opened)

    async def maintain(
        self, *, lookahead_weeks: int, retention_weeks: int
    ) -> OutboxMaintenanceResult:
        """Ensure upcoming partitions exist and drop ones past retention.

        A no-op (with a warning) when the database does not ship the partition
        functions, e.g. when the outbox is a plain, unpartitioned table.
        """
        async with self._db.connect() as conn:
            if not await self._probe(conn):
                self._logger.warning(
                    "Outbox partition functions %s/%s not found; the outbox table "
                    "is not partitioned in this database — skipping maintenance",
                    self.qualified_name(CREATE_PARTITIONS_FN),
                    self.qualified_name(DROP_PARTITIONS_FN),
                )
                return OutboxMaintenanceResult()

            created = await self._call(conn, CREATE_PARTITIONS_FN, lookahead_weeks)
            dropped = await self._call(conn, DROP_PARTITIONS_FN, retention_weeks)

        self._logger.info(
            "Outbox partition maintenance done: created=%s dropped=%s",
            created or "none",
            dropped or "none",
        )
        return OutboxMaintenanceResult(created=created, dropped=dropped)

    async def _probe(self, conn) -> bool:
        result = await conn.execute(
            text(
                "SELECT to_regproc(:create_fn) IS NOT NULL "
                "AND to_regproc(:drop_fn) IS NOT NULL"
            ),
            {
                "create_fn": self.qualified_name(CREATE_PARTITIONS_FN),
                "drop_fn": self.qualified_name(DROP_PARTITIONS_FN),
            },
        )
        return bool(result.scalar())

    async def _call(self, conn, function: str, weeks: int) -> List[str]:
        result = await conn.execute(
            text(f"SELECT partition_name FROM {self.qualified_name(function)}(:weeks)"),
            {"weeks": weeks},
        )
        return [row.partition_name for row in result]
