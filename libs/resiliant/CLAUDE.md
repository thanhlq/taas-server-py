# Resiliant

Durable resilience patterns (Temporal-like: "applications that never fail") on
Postgres + Kafka: transactional outboxes, DLQ, idempotency, sagas, schedules.

**Twin of `taas-server-js/packages/resiliant` (`@taas/resiliant`)**: same `resiliant_*` tables in the
shared database (`taas_next_test`), same statuses, SQL, relay / lease / CAS semantics and settings
names. A row written by one language is processed by the other. When behaviour changes, change both.

- **Contracts** (interfaces, configs, enums) stay in `libs/foundation/src/foundation/resiliant` —
  definitions only. Every implementation (bulkhead, circuit breaker, timeout, fallback, retry,
  `ResilientExecutor`, saga service, DLQ, idempotency, outbox, schedule) **and every settings
  loader** (`*_settings.py`, reading env) lives here. Foundation code reaches implementations
  only through the registry (`FoundationFactory.use_resiliant` registers them by contract).
- **Models** (`src/resiliant/models`, base `models/base.py`) map the tables column for column:
  bigint identity ids, `text` + CHECK enumerations (`EnumText`, lowercase values), `jsonb`,
  `timestamptz`. The `db` consistency check fails at startup on any difference, both ways.
- **DDL is NOT Alembic's**: `resiliant.migrations` applies the drizzle migrations of
  `@taas/resiliant`, vendored byte for byte in `src/resiliant/migrations/drizzle`
  (`scripts/sync-resiliant-migrations.sh`; `tests/unit_local/test_migrations_parity.py` fails on
  drift) with drizzle's own history (`drizzle.__resiliant_migrations`). `python -m db.migrations
  upgrade` runs it first; Alembic ignores `resiliant_*`. Schema change = drizzle migration in
  taas-server-js, then sync. `python -m resiliant.migrations upgrade|status|drop`.
- SQL helpers shared by every repository (database clock, inlined status literals, `clip`, backoff,
  idle sleep): `src/resiliant/sql.py` (twin of `src/db/index.ts` + runtime).
- Entry point: `ResiliantServiceFactory` (registered via `FoundationFactory.use_resiliant`);
  per-folder builders are in each `factory.py` (see root CLAUDE.MD convention).

## Idempotency (Postgres or Redis)

`IDEMPOTENCY_BACKEND=postgres|redis` (settings: `idempotency/idempotency_settings.py`) picks the
`IIdempotencyStore` behind `IdempotencyService` (`idempotency/factory.py`):

- `guard(session, event_id, handler_name)` (context manager yielding `should_process`) and
  `run_once(..., work=)` (JS-style outcome) **claim the key first**, then run the work;
- `postgres` → `resiliant_processed_events`: `INSERT … ON CONFLICT DO NOTHING RETURNING` in a
  savepoint of the caller's session; the work failing rolls the claim back; a concurrent duplicate
  waits on the unique index, then skips. Expiry: `cleanup_expired` (maintenance);
- `redis` → lease protocol on `<prefix>:<handler>:<event_id>`: `SET lease:<token> NX PX
  IDEMPOTENCY_LEASE_MS`, work, then the record with the TTL; another worker's lease →
  `IdempotencyInProgressError` (nack); a failed work deletes its own lease. Connection
  `IDEMPOTENCY_REDIS_HOST` (local: the `store` Redis, `localhost:16380`).

Details and trade-offs: `docs/developers/resiliant-idempotency.md`.

## Retry

`resiliant.retry` (`TenacityRetry` = `Retry`, shared `retry` decorator instance). Foundation's
event processors get policies from the registered `IRetryPolicyFactory`
(`get_retry_policy_factory()`); `messaging_kafka` imports `resiliant.retry.retry` directly.

## Outbox (one table per use case)

Generic engine (`src/resiliant/outbox`): `registry` (`OutboxDefinition` → table model),
`outbox_repository` (lock-based claim, CAS outcomes, retention, stats), `outbox_processor` (one relay
step: claim → dispatch → outcome in ONE transaction, `OutboxTargetCircuit`), `dispatchers` (per
`OutboxTarget`), `outbox_poller` (loops the processor: drain, idle backoff, LISTEN/NOTIFY), `factory`.
Settings: the JS `OUTBOX_*` names / defaults. Built-ins:

- `factory.get_messaging_outbox_service()` → `resiliant_outbox_messages` (`get_outbox_service()` is an alias)
- `factory.get_transaction_outbox_service(target=OutboxTarget.MESSAGING)` →
  `resiliant_outbox_transactions`, idempotent on `request_id`

No `processing` status: rows are locked (`FOR UPDATE SKIP LOCKED`) while dispatched, the outcome is
written before commit (a crash rolls back → claimable again). Failures retry with capped backoff and
end in `dead_letter` at `max_retries` — only while the circuit is closed: `breaker_failure_threshold`
distinct failing records = target down (circuit opens, failures stop counting). `preserve_ordering`:
a record waits behind a failing one of its ordering key (same target + channel).
Flow diagram + how to add a use case / target: `docs/developers/resiliant-outbox.md`.

## Saga (twin of `@taas/resiliant/saga`)

`src/resiliant/saga`: `SagaService` (`run` / `resume` / `signal`), `PgSagaRepository` (alias
`SagaRepository`, `resiliant_saga_state`), `MemorySagaRepository` (tests), builders in `factory.py`.
Contracts (`define_saga`, statuses, errors) in `foundation.resiliant.saga`. Behaviour and row shape
are the Node twin's - an instance written by one language is resumed by the other:

- checkpoint (upsert on `saga_id`, own session/commit, never the business transaction) after the
  start, every step, every compensation and the final status; `created_at`/`updated_at` from the
  executor clock; `steps` jsonb = `[{name, status, error}]`, `current_step` = first not completed,
  `last_error` = newest step error (clipped 1000);
- the upsert only updates a row of the same `name` (else `SagaError`); `(name, saga_key)` is unique
  when the key is set - a second `run` for the key raises `SagaError` at its first checkpoint;
- a failed step → `compensating`, completed steps compensated newest first (each marked
  `compensated`, with or without a compensation function) → `aborted` + `SagaAbortedError`
  (`raise_on_abort`); a failing compensation → `failed` + `SagaCompensationError`;
- only `Exception` compensates: cancellation / `BaseException` acts as a crash (instance stays
  resumable). Steps and compensations must be idempotent (a crash re-runs the step in flight);
- `resume` (startup: `repository.list_active(name=...)`, oldest first) continues `running` /
  `compensating`, returns a finished one unchanged, refuses unknown recorded step names;
- `signal(name, key, patch)` merges into the stored context (`jsonb ||`); ignored (instance
  returned) when finished, `None` when unknown. Signal parked sagas only.

## DLQ (twin of `@taas/resiliant/dlq`)

`src/resiliant/dlq`: `DLQService` (`save` / `save_event`, `get`, `list`, `approve` / `cancel` /
`abandon`, `replay`, `archive`, `reset_stale`, `stats`), `DLQHandlerRegistry` (replays by
`handler_name`), `DLQRetryProcessor.process_batch()` (one retry step), settings `dlq_settings.py`
(`DLQ_*`, same names/defaults as JS; malformed raises). Contracts (`DLQStatus`, `DLQ_TRANSITIONS`,
`DeadLetterConfig`, `NewDeadLetter`) in `foundation.resiliant.dlq`. Rules:

- service calls take the caller's session and never commit; only `DLQRetryProcessor` owns
  transactions (claim commits before handlers run, then one commit per settled record);
- every status change is a compare-and-set checked against `DLQ_TRANSITIONS` before any SQL
  (`DeadLetterError` when illegal; operator actions return `False` when someone acted first);
- retries lease rows (`pending`/`approved` → `processing`, `FOR UPDATE SKIP LOCKED`, inlined status
  literals = partial index `resiliant_dlq_events_due_idx`); failure → `pending` + backoff
  (`next_attempt_at`, database clock) until `max_retries` (explicit > `DLQ_HANDLER_MAX_RETRIES` >
  default) → `abandoned`; `approve` gives a fresh budget; `reset_stale` returns leases older than
  `DLQ_CLAIM_TIMEOUT_MS`;
- rows are never deleted: `archive` moves terminal rows (`resolved`/`cancelled`/`abandoned`) older
  than `DLQ_ARCHIVE_AFTER_DAYS` to `resiliant_dlq_events_archive` (same id) in one statement.

## Schedule (twin of `@taas/resiliant/schedule`)

`src/resiliant/schedule`: `ScheduleService` (`schedule_once(run_at)` / `schedule_after(delay_ms)` /
`schedule_interval(interval_seconds, start_at?, max_runs?)` / `schedule_cron(cron_expr, max_runs?)`,
`cancel`, `exists_active`, `stats`), `ScheduleRepository`, `SchedulerPoller` (`register(job_name, cb)`,
`process_batch()` = one step, `start`/`stop`/`run`, `wake`, `check_health`), dependency-free UTC
`parse_cron` / `next_cron_time` (`cron.py`, same results as `cron.ts`), `compute_next_run`, settings
`schedule_settings.py` (`SCHEDULE_*`, same names/defaults as JS + Python-only `SCHEDULE_ENABLED`;
malformed raises), builders `factory.py`. Contracts in `foundation.resiliant.schedule`. Rules:

- creates / cancel join the caller's session and never commit; a create returns `None` when an
  active job holds its `unique_key` (`ON CONFLICT` on the partial unique index = singleton);
- the poller leases due rows (`scheduled` → `running` + `claimed_at`, `FOR UPDATE SKIP LOCKED`,
  inlined `'scheduled'` = `resiliant_scheduled_jobs_due_idx`) and commits the claim before firing;
  each outcome is a CAS on `running` in its own short transaction (a cancel wins over a fire);
- a job with `channel` is published (`publish(channel=, message=payload, ordering_key=, headers=)`),
  otherwise the callback of `job_name` runs; neither → the job fails loudly;
- failure → same occurrence retried after `SCHEDULE_RETRY_BACKOFF_MS` until the job's `max_retries`
  (default `SCHEDULE_MAX_RETRIES`) → `failed`; success resets `attempts`, recurring jobs move on
  (interval keeps its phase, cron continues from now; missed occurrences skipped), `max_runs` → `done`;
- the maintenance tick resets leases older than `SCHEDULE_CLAIM_TIMEOUT_MS` and logs `stats`.

## Maintenance & visibility

`maintenances/`: `ResiliantMaintenance.run()` (purge published outbox rows older than
`OUTBOX_RETENTION_DAYS`, expired idempotency keys, archive terminal DLQ rows, reset stale DLQ leases;
bounded sweeps), scheduled as the singleton cron job `resiliant:maintenance` (`unique_key`;
`RESILIANT_MAINTENANCE_CRON`, default `0 2 * * *`) — the same job as the Node twin, so exactly one
replica of either language runs it. `visibility.py`: `ResilienceVisibilityService.snapshot(session)`
→ `{healthy, problems, outboxes, dlq, saga, schedule}` (same rules as JS).

## Tests

`uv run --package resiliant pytest libs/resiliant/tests/unit libs/resiliant/tests/unit_local`
(`tests/unit`: real PostgreSQL from `.env.test`, or an isolated database with
`RESILIANT_TEST_DATABASE_URL`; the fixtures migrate it and truncate every resiliant table per test —
never run them while services use that database. Redis cases use the `store` Redis,
`IDEMPOTENCY_TEST_REDIS_URL`, default `redis://localhost:16380/15`, and skip without it).
`tests/unit_local` covers the pure patterns and the migration parity.
