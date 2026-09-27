# resiliant.models

SQLAlchemy models of the resiliant package (tables prefixed `RESILIANT_TABLE_PREFIX`,
default `resiliant_`). Enums/contracts come from `foundation.resiliant`.

- Migrated by the single Alembic tree in `libs/db` (`db/migrations/env.py` imports this package).
- Outbox tables share `OutboxRecordMixin` (`outbox.py`); a new use case = a new mixin subclass
  + `register_outbox(...)` + a migration.
