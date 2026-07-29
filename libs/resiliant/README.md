# resiliant

Database-backed resilience patterns — the pattern-stack equivalent of the
Temporal.io feature set, built on Postgres + Kafka + the services this platform
already runs. Definitions (configs, enums, protocols, executors) live in
`foundation.resiliant`; the durable, Postgres-backed implementations live here;
the SQLAlchemy models live in `db.models.resiliant`.

## Capabilities

| Capability | Temporal equivalent | Entry point |
|---|---|---|
| Transactional outbox + relay | reliable event emit | `OutboxService`, `OutboxPoller` |
| Idempotency (`ON CONFLICT`) | exactly-once activity | `IdempotencyService.guard` |
| Dead-letter queue | poison-message handling | `DLQService` |
| Durable saga state | durable workflow, signals, queries, compensation | `SagaRepository` + `foundation…SagaService` |
| Durable timers / schedules / cron | `workflow.sleep`, Schedules | `ScheduleService`, `SchedulerPoller` |
| Composed guards | activity timeout / retry | `foundation…ResilientExecutor` |
| Visibility | Temporal Web UI | `ResilienceVisibilityService.snapshot` |

Everything is obtained through `ResiliantServiceFactory` (registered via
`FoundationFactory.use_resiliant(...)`) or the static `ResiliantServiceBuilder`.

```python
factory = ResiliantServiceFactory()
outbox   = factory.get_outbox_service()
saga     = factory.get_saga_service()
schedule = factory.get_schedule_service()
```

The `outbox_worker` app hosts both the `OutboxPoller` and the `SchedulerPoller`
as co-located pure pollers (no extra deployable).

## Versioning policy (safe in-flight deploys)

This is the pattern-stack substitute for `workflow.patched()`. Saga steps are
looked up by **string name**, never by index, which makes flows safe to evolve
while instances are in flight — *provided* the following discipline is kept:

- **Add steps freely.** A new step inserted into a `SagaDefinition` is skipped
  naturally by any in-flight saga whose `current_step` is already past the
  insertion point (lookup is by name, so unknown/earlier names still resolve).
- **Never rename or drop a step name** while sagas referencing it may be in
  flight. A renamed step reads as a *new* step and an orphaned old record.
- **Migrations are additive-only** — add nullable columns; never rename/drop a
  column that a persisted `context`/`steps` JSON payload depends on. This keeps
  old rows decodable across a deploy.
- **Gate behavioural changes behind a settings flag.** New sagas run the new
  branch; in-flight sagas complete on the path they started. Roll back by
  flipping the flag — in-flight sagas are unaffected.
- **Scheduled jobs** follow the same rule: `job_name` is the contract between a
  producer and its dispatcher/channel — treat it as a stable, additive-only key.

Enforce these in code review. They cost almost nothing and are what let the
DB-backed stack deploy as safely as Temporal's versioned histories.
