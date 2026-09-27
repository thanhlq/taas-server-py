# Resiliant idempotency — components and communication

At-most-once handling of at-least-once messages, with a configurable store
(2026-09 refactor). Contracts: `libs/foundation/src/foundation/resiliant/idempotency.py`;
implementation: `libs/resiliant/src/resiliant/idempotency/`.

## Components

| Component | Where | Role |
| --- | --- | --- |
| `IdempotencyConfig`, `IdempotencyBackend`, `IIdempotencyStore`, `IIdempotencyService`, `DuplicateEventError` | `foundation.resiliant.idempotency` | definitions only |
| `IdempotencySettings` / `get_idempotency_config()` | `resiliant.idempotency.idempotency_settings` | reads `IDEMPOTENCY_*` env |
| `build_idempotency_service()` / `build_idempotency_store()` | `resiliant.idempotency.factory` | picks the store from `config.backend` |
| `IdempotencyService` | `resiliant.idempotency.idempotency_service` | `guard`, `is_processed`, `mark_processed`, metrics, logging |
| `PostgresIdempotencyStore` | `resiliant.idempotency.stores.postgres` | table `resiliant_processed_events` |
| `RedisIdempotencyStore` | `resiliant.idempotency.stores.redis` | keys `<prefix>:<handler>:<event_id>` |
| `EventProcessorFast` (consumer) | `foundation.messaging.events` | resolves `IIdempotencyService` from the registry |

Wiring: `ResiliantServiceFactory().get_idempotency_service()` → `FoundationFactory.use_resiliant`
registers it as `IIdempotencyService`; foundation never imports the implementation.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `IDEMPOTENCY_BACKEND` | `postgres` | `postgres` \| `redis` |
| `IDEMPOTENCY_REDIS_HOST` / `_PASSWORD` | cache Redis (`TAAS_CACHE_REDIS_HOST` / `_PASSWORD`) | `redis://host:port/db`; sentinel/cluster via `store_redis` |
| `IDEMPOTENCY_REDIS_KEY_PREFIX` | `idempotency` | key namespace |
| `IDEMPOTENCY_TTL_DAYS` | `30` | Redis key TTL / Postgres cleanup age |
| `IDEMPOTENCY_STRICT_MODE`, `_LOG_DUPLICATES`, `_ENABLE_METRICS`, `_CLEANUP_BATCH_SIZE`, `_DB_QUERY_TIMEOUT_MS` | | behaviour flags |

## Flow (one handler, one event)

```text
EventProcessorFast._process(event)
  └─ async with session_factory() as session:
       └─ IIdempotencyService.guard(session, event_id, handler_name, raise_on_duplicate=True)
            entry : store.is_processed(session, "<handler>:<event_id>")
                      postgres → SELECT id … LIMIT 1        redis → EXISTS <prefix>:<handler>:<event_id>
                    duplicate → DuplicateEventError → processor returns success (skipped)
            body  : handler (through the retry policy)
            exit  : store.mark_processed(…)  (only on clean exit — a failure stays retryable)
                      postgres → INSERT … ON CONFLICT DO NOTHING RETURNING id  (same session)
                      redis    → SET key <json> NX EX ttl_days*86400
       └─ session.commit()   ← postgres: key commits with the session; redis: already written
```

Both stores claim atomically, so concurrent workers racing on one key get exactly
one winner (`mark_processed` → `True`).

## Choosing a backend

| | Postgres | Redis |
| --- | --- | --- |
| Atomic with business writes | yes (same session / transaction) | no — a crash after the business commit and before `SET` re-runs the handler on redelivery |
| Expiry | periodic `cleanup_expired` (batched DELETE) | automatic (key TTL); `cleanup_expired` is a no-op |
| Load on the main DB | one SELECT + INSERT per handled event | none |
| Needs | the migrated table | a reachable Redis |

Default is Postgres (correctness first); use Redis for high-volume consumers whose
handlers are naturally idempotent.
