# Temporal Feature Completion Plan — `resiliant` Pattern Stack

> **Decision (unchanged):** We do **not** run a Temporal server. We complete the
> Temporal-equivalent capabilities inside the code we already own — Postgres +
> Kafka + the `resiliant` / `foundation.resiliant` libraries. See
> [`temporal-vs-patterns-comparison.md`](./temporal-vs-patterns-comparison.md)
> for the rationale and [`resilience-patterns-reference.md`](./resilience-patterns-reference.md)
> for pattern theory. This doc is the **build plan**: what is done, what is
> half-built, and the concrete steps to finish each remaining Temporal feature.

---

## 1. Where the code actually is today

| Layer | Location | Role |
|---|---|---|
| **Definitions** (configs, enums, `Protocol` repos, service classes) | `libs/foundation/src/foundation/resiliant/` | The contracts + generic service logic, storage-agnostic |
| **DB-backed implementations** | `libs/resiliant/src/resiliant/` | Postgres implementations of the `Protocol` repos |
| **DB models** | `libs/db/src/db/models/resiliant/` | SQLAlchemy tables |
| **Runtime relay** | `apps/outbox_worker` (`OutboxPoller`) | Publishes staged events to Kafka |
| **Consumer pipeline** | `apps/ews_worker` (`EwsWorker` + `EventProcessor`) | Consumes topics via `messaging_faststream` |

**Rule of thumb:** a Temporal feature is "done" only when it has all three —
a definition in `foundation.resiliant`, a DB impl in `libs/resiliant`, and a
model in `db.models.resiliant` — **and** it is wired into a running worker.

---

## 2. Status of every Temporal feature

| Temporal feature | Our equivalent | Definition | DB impl | Wired | Status |
|---|---|---|:--:|:--:|:--:|
| Exactly-once activity | `IdempotencyService` (`ON CONFLICT`) | ✅ | ✅ | ✅ | **DONE** |
| Reliable event emit (outbox) | `OutboxService` + `OutboxPoller` | ✅ | ✅ | ✅ | **DONE** |
| Dead-letter queue | `DLQService` | ✅ | ✅ | ✅ | **DONE** |
| Activity retry / back-off | `retry` (`TenacityRetry`) | ✅ | n/a | ✅ | **DONE** |
| Durable workflows (crash & resume) | `SagaService` + `saga_state` | ✅ | ❌ | ❌ | **GAP 1** |
| Compensation / rollback | `SagaStep.compensate` | ✅ | ❌ | ❌ | **GAP 1** |
| Signals (external input) | Kafka event → update `saga_state` | ✅ | ❌ | ❌ | **GAP 1** |
| Queries (read running state) | `SELECT` on `saga_state` | ✅ | ❌ | ❌ | **GAP 1** |
| Child workflows (fan-out) | Saga step → `stage_deferred()` outbox events | ✅ | ✅ | ⚠️ | **GAP 1** (pattern, not code) |
| **Durable timers** (sleep days/months) | `scheduled_at` column + poller | ❌ | ❌ | ❌ | **GAP 2** |
| **Schedules / cron** | `scheduled_jobs` + `croniter` | ❌ | ❌ | ❌ | **GAP 2** |
| Activity timeout | `TimeoutService` | ✅ | n/a | ❌ | **GAP 3** |
| Fail-fast on bad dependency | `CircuitBreakerService` | ✅ | ❌ | ❌ | **GAP 3** |
| Concurrency isolation | `BulkheadService` | ✅ | n/a | ❌ | **GAP 3** |
| Graceful degradation | `FallbackService` | ✅ | n/a | ❌ | **GAP 3** |
| Visibility UI / search | SQL + `/health/resilience` + Grafana | — | — | ❌ | **GAP 4** |
| Workflow versioning | String step names + additive migrations | — | — | — | **GAP 5** (policy) |

The heavy engine work is **already built**. What remains is (1) persisting the
saga engine, (2) adding a durable timer/scheduler — the one true missing
primitive — (3) wiring the guard services into the consumer pipeline, and
(4) a thin visibility layer.

---

## 3. GAP 1 — Persist & wire the Saga engine

`SagaService` in `foundation/resiliant/saga.py` already executes a
`SagaDefinition` (ordered `SagaStep`s with `compensate` callbacks) and calls
`ISagaRepository.save(instance)` / `get(saga_id)` after each step. There is no
DB implementation, so state lives only in memory → no crash-resume. Give it a
Postgres repo and it becomes Temporal's durable workflow + signals + queries +
compensation all at once.

**Steps**

1. **Model** — add `libs/db/src/db/models/resiliant/_saga_models.py` mirroring
   the existing `_outbox_models.py`:
   ```
   saga_state(
     saga_id PK, name, status, current_step, context JSONB,
     attempts, retry_after, last_error, created_at, updated_at,
     UNIQUE(name, saga_key)          -- saga_key derived from context, the "resume pointer" anchor
   )
   ```
   Index `(status, retry_after)` for the retry poller (GAP 2) and
   `(name, saga_key)` for signals/queries.

2. **Repository** — add `libs/resiliant/src/resiliant/saga/` with
   `SagaRepository(ISagaRepository)` (`save`/`get` → upsert/select the row,
   `context` ⇄ JSONB) and a `factory.py` (`build_saga_service`), matching the
   `outbox/` package layout. Export from `resiliant/__init__.py` and add
   `get_saga_service()` to `ResiliantServiceFactory`.

3. **Signals** — a Kafka handler looks up the saga by `(name, saga_key)`,
   merges the payload into `context`, sets `status=RUNNING`; the next
   `advance` picks up the injected data. No new mechanism — it is a normal
   subscriber writing to `saga_state`.

4. **Queries** — expose `get_saga_service().get(saga_id)` (and a
   `by_saga_key` helper) behind a read-only endpoint (feeds GAP 4).

5. **Child workflows** — already expressible today: a saga's final step calls
   `OutboxService.save_event()` once per child (`stage_deferred`), each event
   starts an independent child saga. Document this as the sanctioned fan-out
   pattern; no new code beyond GAP 1.

**Wiring:** in `EwsWorker._init_services`, register the saga service on the
factory; saga-backed handlers call `saga_service.run(definition, context, saga_id=...)`
inside the idempotency guard (see §7).

---

## 4. GAP 2 — Durable timers & scheduler (the only truly missing primitive)

Nothing in the repo does `sleep(days)`, `next_run_at`, cron, or backfill — this
is the one Temporal capability with **no** current equivalent, and it unlocks
subscription billing, KYC "wait up to 30 days", withdrawal confirmations, and
saga retry back-off. Build it as a DB-polled timer, reusing the exact
`SELECT ... FOR UPDATE SKIP LOCKED` engine already proven in `OutboxPoller`.

**Steps**

1. **Model** — `db.models.resiliant._schedule_models`:
   ```
   scheduled_job(
     id PK, job_name, kind ENUM('once','cron'), cron_expr NULL,
     next_run_at, last_run_at, status ENUM('SCHEDULED','RUNNING','DONE','FAILED'),
     payload JSONB, created_at, updated_at)
   INDEX (status, next_run_at)
   ```

2. **Service** — `foundation/resiliant/schedule.py`: `IScheduleRepository`
   (`due_batch(now, limit)`, `save`, `reschedule`) + `SchedulerService` that,
   per due row, publishes an outbox event or invokes a registered callback,
   then advances `next_run_at` via `croniter` (add `croniter` to
   `libs/foundation` deps). DB impl in `libs/resiliant/src/resiliant/schedule/`.

3. **Runtime** — add a `SchedulerPoller` (copy `OutboxPoller`'s loop: staggered
   start, `SKIP LOCKED`, adaptive interval, graceful `stop()`). Host it **in the
   existing `outbox_worker`** as a second `asyncio` task — no new deployable.
   A 30–60 s poll interval is ample for business-level timers.

4. **Saga retry poller** — the same `due_batch` loop, keyed on
   `saga_state.retry_after <= now AND status='PENDING_RETRY'`, calling saga
   `advance`. This closes the retry half of GAP 1.

> If you ever need sub-second durable timers at >100k/s, that is the one
> trigger where a real Temporal server beats DB polling — see §9.

---

## 5. GAP 3 — Wire the guard services into the pipeline

`TimeoutService`, `CircuitBreakerService`, `BulkheadService`, `FallbackService`
are fully written in `foundation.resiliant` but never invoked. They wrap the
**external-call** portion of a handler/activity (RPC nodes, KYC provider, chain
RPC). Only the circuit breaker needs storage.

**Steps**

1. **Circuit breaker persistence** — implement `ICircuitBreakerRepository`
   (`get(name)` / `save(snapshot)`) in `libs/store_redis` so breaker state is
   fleet-wide (one open breaker trips all workers). Redis TTL = the breaker's
   cool-down. Timeout/bulkhead/fallback are per-process and need no store.

2. **Compose a `@resilient_call` helper** in `foundation.resiliant` that stacks
   `fallback(timeout(circuit_breaker(bulkhead(fn))))` from a single config, so
   activity code writes one decorator, not four. Apply it to the Kaspa RPC
   client (`libs/block-kaspa`) and any outbound provider call first.

---

## 6. GAP 4 — Visibility (replaces the Temporal UI)

You already have OpenTelemetry wired end-to-end in
`foundation/observability` (traces on SQLAlchemy, FastAPI, aiokafka). Add the
resilience-specific read surface on top:

1. **`GET /health/resilience`** — one query grouping `saga_state`,
   `outbox_event`, `dlq_event`, `scheduled_job` by `status`. Returns e.g.
   `{"saga": {"RUNNING": 3, "PENDING_RETRY": 1}, "dlq": {"PENDING": 0}}`.
   This is the "is anything stuck?" dashboard in one endpoint.
2. **Grafana panels** on those same counts + `age(now, retry_after)` for the
   oldest stuck row. Alert: `dlq.PENDING > 0` or any saga `PENDING_RETRY`
   older than 1 h.
3. **Trace attributes** — set `saga.id`, `saga.step`, `event.id` as span
   attributes in `EventProcessor` so a stuck saga is one trace-search away.

---

## 7. The canonical handler pipeline (how the pieces compose)

Wire this order once, in `EventProcessor` / the saga-backed handler, so every
new flow inherits it for free:

```
Kafka event
  └─ idempotency.guard(event_id)          # GAP 0 — done; skip duplicates
       └─ saga_service.run(definition)     # GAP 1 — durable, resumable state
            └─ step activity
                 ├─ resilient_call(...)     # GAP 3 — timeout+breaker+bulkhead+fallback on external I/O
                 └─ outbox.save_event(...)  # done — stage child/next events in same txn
       on step failure  → saga PENDING_RETRY + retry_after   # GAP 2 poller resumes
       on retries spent → DLQService.save_event(...)          # done
       long wait/cron   → scheduled_job row                   # GAP 2
```

Everything above the `resilient_call` line commits in **one Postgres
transaction**, which is the atomicity guarantee that made us choose this stack
over Temporal in the first place.

---

## 8. GAP 5 — Versioning policy (no code, just discipline)

Saga steps are looked up by **string name**, not index, so:

- **Add** steps freely; in-flight sagas whose `current_step` is already past
  the insertion point skip the new step naturally.
- **Never rename or drop** a step name while sagas referencing it are in flight.
- **Migrations are additive-only** (new nullable columns) so old `context`
  JSON stays valid across a deploy.
- Gate new branches behind a settings flag; new sagas use the new runner,
  in-flight sagas finish on the old path.

Write this as a one-paragraph rule in `libs/resiliant/README` and enforce in
review — it is the cheap equivalent of `workflow.patched()`.

---

## 9. Explicitly out of scope — when to revisit real Temporal

Adopt an actual Temporal server **only** if one of these becomes true (none do
today):

- Sub-second durable-timer precision at >100k timers/sec.
- >20 engineers authoring new long-running flows concurrently.
- Regulator demands a tamper-proof, append-only execution log (our `saga_state`
  is a mutable row).
- We ship a visual workflow product to end users.

Until then, finishing GAP 1–4 gives us every Temporal feature we use, on infra
we already operate.

---

## 10. Suggested order of work

| # | Task | Effort | Unlocks |
|---|---|---|---|
| 1 | GAP 2 scheduler/timer (model + `SchedulerPoller` in `outbox_worker`) | M | Billing, KYC waits, **saga retry** |
| 2 | GAP 1 `SagaRepository` + `saga_state` model + factory wiring | M | Durable workflows, signals, queries, compensation |
| 3 | GAP 4 `/health/resilience` + Grafana + trace attrs | S | Operability of 1 & 2 |
| 4 | GAP 3 `resilient_call` helper + Redis breaker repo | M | Fault isolation on external calls |
| 5 | GAP 5 versioning rule in README | S | Safe deploys |

> Do the Part-1 workspace fixes (undeclared `ews_api` deps, CI, stale
> `[tool.ty]`/pyright paths) **before** shipping any of the above — otherwise a
> scoped prod build of the new saga/scheduler code will fail to import.
