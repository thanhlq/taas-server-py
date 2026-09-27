# Resiliant

Durable resilience patterns (Temporal-like: "applications that never fail") on
Postgres + Kafka: transactional outboxes, DLQ, idempotency, sagas, schedules.

- **Contracts** (interfaces, configs, enums) stay in `libs/foundation/src/foundation/resiliant` —
  definitions only. Every implementation (bulkhead, circuit breaker, timeout, fallback, retry,
  `ResilientExecutor`, saga service, DLQ, idempotency, outbox, schedule) **and every settings
  loader** (`*_settings.py`, reading env) lives here. Foundation code reaches implementations
  only through the registry (`FoundationFactory.use_resiliant` registers them by contract).
- **Implementations and their SQLAlchemy models** live here: `src/resiliant/models`
  (tables prefixed `resiliant_`). This package does not depend on `libs/db`; `libs/db`
  imports `resiliant.models` in `db/migrations/env.py`, so its single Alembic tree
  migrates these tables.
- Entry point: `ResiliantServiceFactory` (registered via `FoundationFactory.use_resiliant`);
  per-folder builders are in each `factory.py` (see root CLAUDE.MD convention).

## Idempotency (Postgres or Redis)

`IDEMPOTENCY_BACKEND=postgres|redis` (settings: `idempotency/idempotency_settings.py`) picks the
`IIdempotencyStore` behind `IdempotencyService` (`idempotency/factory.py`):

- `postgres` → `resiliant_processed_events` (`INSERT … ON CONFLICT`); the key commits with the
  business transaction (same session). Expiry: `cleanup_expired`.
- `redis` → `SET <prefix>:<handler>:<event_id> NX EX ttl`; session ignored, keys expire by
  themselves. Connection `IDEMPOTENCY_REDIS_HOST`, default the cache Redis (`TAAS_CACHE_REDIS_HOST`).

Details and trade-offs: `docs/developers/resiliant-idempotency.md`.

## Retry

`resiliant.retry` (`TenacityRetry` = `Retry`, shared `retry` decorator instance). Foundation's
event processors get policies from the registered `IRetryPolicyFactory`
(`get_retry_policy_factory()`); `messaging_kafka` imports `resiliant.retry.retry` directly.

## Outbox (one table per use case)

Generic engine (`src/resiliant/outbox`): `registry` (`OutboxDefinition` → table model),
`outbox_repository` (claim / retry / stats for any table), `dispatchers` (per
`OutboxTarget`, routed by `record.target`), `outbox_poller` (one per table),
`factory` (builds all). Built-ins:

- `factory.get_messaging_outbox_service()` → `resiliant_outbox_messages` (`get_outbox_service()` is an alias)
- `factory.get_transaction_outbox_service(target=OutboxTarget.MESSAGING)` →
  `resiliant_outbox_transactions`, idempotent on `request_id`

Failures retry with backoff (`next_attempt_at`) and end in `DEAD_LETTER` at `max_retries`.
Flow diagram + how to add a use case / target: `docs/developers/resiliant-outbox.md`.

## Tests

`uv run --package resiliant pytest libs/resiliant/tests/unit libs/resiliant/tests/unit_local`
(`tests/unit` needs the migrated DB from `.env.test` — resiliant tables are truncated per test — and
a local Redis for the Redis idempotency cases, `IDEMPOTENCY_TEST_REDIS_URL`, default
`redis://localhost:6379/15`; they skip without it). `tests/unit_local` covers the pure patterns.
