# Resiliant idempotency — components and communication

At-most-once handling of at-least-once messages, with a configurable store — same
protocol and storage as `@taas/resiliant` (taas-server-js). Contracts: `libs/foundation/src/foundation/resiliant/idempotency.py`;
implementation: `libs/resiliant/src/resiliant/idempotency/`.

## Components

| Component | Where | Role |
| --- | --- | --- |
| `IdempotencyConfig`, `IdempotencyBackend`, `IIdempotencyStore`, `IIdempotencyService`, `DuplicateEventError`, `IdempotencyInProgressError` | `foundation.resiliant.idempotency` | definitions only |
| `IdempotencySettings` / `get_idempotency_config()` | `resiliant.idempotency.idempotency_settings` | reads `IDEMPOTENCY_*` env |
| `build_idempotency_service()` / `build_idempotency_store()` | `resiliant.idempotency.factory` | picks the store from `config.backend` |
| `IdempotencyService` | `resiliant.idempotency.idempotency_service` | `guard` (claim first), `run_once`, `is_processed`, `mark_processed`, `cleanup_expired`, metrics |
| `PostgresIdempotencyStore` | `resiliant.idempotency.stores.postgres` | table `resiliant_processed_events` |
| `RedisIdempotencyStore` | `resiliant.idempotency.stores.redis` | keys `<prefix>:<handler>:<event_id>` |
| `EventProcessorFast` (consumer) | `foundation.messaging.events` | resolves `IIdempotencyService` from the registry |

Wiring: `ResiliantServiceFactory().get_idempotency_service()` → `FoundationFactory.use_resiliant`
registers it as `IIdempotencyService`; foundation never imports the implementation.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `IDEMPOTENCY_BACKEND` | `postgres` | `postgres` \| `redis` |
| `IDEMPOTENCY_REDIS_HOST` / `_PASSWORD` | cache Redis (`TAAS_CACHE_REDIS_HOST` / `_PASSWORD`); locally set to the `store` Redis `localhost:16380` | `host:port`; sentinel/cluster via `store_redis` |
| `IDEMPOTENCY_REDIS_KEY_PREFIX` | `idempotency` | key namespace |
| `IDEMPOTENCY_TTL_DAYS` | `30` | Redis key TTL / Postgres cleanup age |
| `IDEMPOTENCY_LEASE_MS` | `60000` | Redis: lease of a key while its work runs |
| `IDEMPOTENCY_STRICT_MODE`, `_LOG_DUPLICATES`, `_ENABLE_METRICS`, `_CLEANUP_BATCH_SIZE` | | behaviour flags |

## Flow (one handler, one event)

```text
EventProcessorFast._process(event)
  └─ async with session_factory() as session:
       └─ IIdempotencyService.guard(session, event_id, handler_name, raise_on_duplicate=True)
            claim : postgres → SAVEPOINT; INSERT … ON CONFLICT DO NOTHING RETURNING id
                               (a concurrent duplicate waits on the unique index, then skips)
                    redis    → record present? duplicate · SET lease:<token> NX PX lease_ms
                               (someone else's lease → IdempotencyInProgressError: nack)
                    duplicate → DuplicateEventError → processor returns success (skipped)
            body  : handler (through the retry policy)
            exit  : success → postgres: savepoint released (commits with the session)
                               redis: SET record PX ttl_days
                    failure → postgres: savepoint rolled back · redis: own lease deleted
       └─ session.commit()
```

## Choosing a backend

| | Postgres | Redis |
| --- | --- | --- |
| Atomic with business writes | yes (same session / transaction) | no — a crash after the business commit leaves a lease that expires: the handler runs again on redelivery |
| Expiry | periodic `cleanup_expired` (batched DELETE) | automatic (key TTL); `cleanup_expired` is a no-op |
| Load on the main DB | one INSERT per handled event | none |
| Needs | the migrated table | a reachable Redis |

Default is Postgres (correctness first); use Redis for high-volume consumers whose
handlers are naturally idempotent.
