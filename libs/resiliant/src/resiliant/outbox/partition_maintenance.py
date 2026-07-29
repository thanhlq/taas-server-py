"""
Outbox partition maintenance.

Wraps the two PL/pgSQL functions shipped with the ``message_outbox`` migration
(``81_message_outbox.yml``) so they can be driven from application code:

  - ``{prefix}create_message_outbox_partitions(weeks_ahead)`` — idempotently
    creates the upcoming weekly partitions (skips any that already exist).
  - ``{prefix}drop_old_message_outbox_partitions(retention_weeks)`` — drops
    weekly partitions older than the retention window.

The outbox table lives in the *main* application database, so this maintainer
talks to ``core.db.db_manager``. The tenant prefix is supplied by the caller
(which already holds a settings instance), so this class does not load settings
itself and can be instantiated once and reused.

Intended to be driven by a single ``@faust_app.timer(on_leader=True)``, so no
cross-process locking is needed here.
"""

from __future__ import annotations
from foundation.db.advanced_db_manager import MainDatabase, AdvancedDBManager
from foundation.observability.log_factory import LogFactory

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text



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

    async def maintain(
        self, *, lookahead_weeks: int, retention_weeks: int
    ) -> OutboxMaintenanceResult:
        """Ensure upcoming partitions exist and drop ones past retention."""
        async with self._db.connect() as conn:
            created = await self._call(
                conn, "create_message_outbox_partitions", lookahead_weeks
            )
            dropped = await self._call(
                conn, "drop_old_message_outbox_partitions", retention_weeks
            )

        self._logger.info(
            "Outbox partition maintenance done: created=%s dropped=%s",
            created or "none",
            dropped or "none",
        )
        return OutboxMaintenanceResult(created=created, dropped=dropped)

    async def _call(self, conn, function: str, weeks: int) -> List[str]:
        result = await conn.execute(
            text(f"SELECT partition_name FROM {self._prefix}{function}(:weeks)"),
            {"weeks": weeks},
        )
        return [row.partition_name for row in result]
