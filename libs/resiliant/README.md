# resiliant

Resilience patterns — the pattern-stack equivalent of the Temporal.io feature set,
built on Postgres + Redis + Kafka. Definitions (configs, enums, errors, protocols) live
in `foundation.resiliant`; **every implementation, settings loader and SQLAlchemy model**
(`resiliant.models`) lives here.

## Capabilities

| Capability | Temporal equivalent | Entry point |
|---|---|---|
| Transactional outboxes + relay (one table per use case) | reliable event emit | `MessagingOutboxService`, `TransactionOutboxService`, `OutboxPoller` |
| Idempotency — Postgres (`ON CONFLICT`) or Redis (`SET NX EX`), `IDEMPOTENCY_BACKEND` | exactly-once activity | `IdempotencyService.guard` |
| Dead-letter queue (shared with taas-server-js) | poison-message handling | `DLQService` (save / approve / cancel / abandon / replay / archive), `DLQRetryProcessor` |
| Durable sagas (shared with taas-server-js) | durable workflow, signals, queries, compensation | `SagaService` (run / resume / signal) + `PgSagaRepository` |
| Durable timers / schedules / cron | `workflow.sleep`, Schedules | `ScheduleService`, `SchedulerPoller` |
| Composed guards | activity timeout / retry | `ResilientExecutor` (bulkhead, circuit breaker, timeout, fallback) |
| Retry policies | activity retry policy | `resiliant.retry` (`TenacityRetry`, `retry`) |
| Visibility | Temporal Web UI | `ResilienceVisibilityService.snapshot` |

Everything is obtained through `ResiliantServiceFactory` (registered via
`FoundationFactory.use_resiliant(...)`) or the static `ResiliantServiceBuilder`.

```python
factory = ResiliantServiceFactory()
events       = factory.get_messaging_outbox_service()        # domain events → broker
transactions = factory.get_transaction_outbox_service(target=OutboxTarget.MESSAGING)
idempotency  = factory.get_idempotency_service()               # IDEMPOTENCY_BACKEND=postgres|redis
saga         = factory.get_saga_service()
schedule     = factory.get_schedule_service()

async with session.begin():  # outbox records commit with the business rows
    await transactions.save_transaction(
        session, request_id='req-1', transaction_type='deposit',
        payload={...}, channel='transactions.inbound', account_ref='acc-42',
    )
```

The `outbox_worker` app runs one `OutboxPoller` per outbox table (narrow with
`OUTBOX_POLL_OUTBOXES=messaging,transaction`) plus the `SchedulerPoller`, as
co-located pure pollers (no extra deployable). Components and message flow:
`docs/developers/resiliant-outbox.md`, `docs/developers/resiliant-idempotency.md`.

## Versioning policy (safe in-flight deploys)

This is the pattern-stack substitute for `workflow.patched()`. Saga steps are
looked up by **string name**, never by index, which makes flows safe to evolve
while instances are in flight — *provided* the following discipline is kept:

- **Add steps freely.** On `resume`, recorded steps are matched by name and a
  step added since the instance started runs in its definition order (a
  completed step is never repeated).
- **Never rename or drop a step name** while sagas referencing it may be in
  flight: `resume` refuses an instance with a recorded name the definition no
  longer has (`SagaError`).
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
