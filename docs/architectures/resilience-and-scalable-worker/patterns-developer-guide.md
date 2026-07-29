# Resilience Patterns — Developer Guide

> **Audience:** engineers building features on the TAAS platform.
> **Scope:** how to *use* the `resiliant` / `foundation.resiliant` patterns in
> day-to-day code — with real finance-domain examples, the config knobs that
> matter, and the traps to avoid.
>
> **Companion docs:** [`temporal-feature-completion-plan.md`](./temporal-feature-completion-plan.md)
> (what exists & why), [`resilience-patterns-reference.md`](./resilience-patterns-reference.md)
> (theory), and the PostgreSQL [`row-locking-guide.md`](../../../../taas-specs/docs/technical/postgresql/row-locking-guide.md)
> (the `FOR UPDATE SKIP LOCKED` primitive every poller relies on).

---

## 0. Mental model & the golden rules

Every pattern here exists to survive one of these failures: a **duplicate**
message, a **crash between steps**, a **partial write** (DB committed, Kafka
not), or a **flaky dependency**. Pick the pattern by the failure you're
defending against — the decision table in §11 maps them.

Four rules that keep you out of trouble:

1. **The database is the source of truth.** Never publish to Kafka *and* write
   the DB in the same handler and hope both land — stage the event in the
   **outbox** so they commit together.
2. **Handlers must be idempotent.** At-least-once delivery means every handler
   *will* see a duplicate eventually. Wrap the body in the **idempotency guard**
   and make the business logic safe to re-run.
3. **One writer per row.** All the pollers claim work with
   `FOR UPDATE SKIP LOCKED`, so you can run N replicas of a worker with zero
   coordination. Keep it that way — don't add "read then update" races.
4. **Money math is additive & append-only.** Never rename/drop a saga step name
   or a DB column that a persisted payload depends on (see §10 Versioning).

---

## 1. Getting the services

At worker/app startup the resilient factory is registered once:

```python
from foundation.factory import FoundationFactory
from resiliant import ResiliantServiceFactory

FoundationFactory.use_resiliant(ResiliantServiceFactory())   # bootstrap.py
```

After that, obtain a service either way:

```python
# A) via the service locator (preferred inside handlers)
from foundation.state import get_service
from foundation.resiliant.outbox import IOutboxService

outbox = get_service(IOutboxService)

# B) via the factory (preferred in wiring / tests)
factory  = ResiliantServiceFactory()
saga     = factory.get_saga_service()
schedule = factory.get_schedule_service()
```

Sessions come from the main DB manager:

```python
from foundation.db.advanced_db_manager import MainDatabase

db = MainDatabase.get_instance()
async with db.new_session() as session:
    ...
```

> **Tip:** services are cheap and stateless beyond their config — never cache a
> session inside one. Always pass the caller's `session` so the write joins the
> surrounding transaction.

---

## 2. Transactional Outbox — never lose an event

**Use when:** a state change must reliably produce a message (credit balance →
emit `BalanceChanged`). Guarantees the DB write and the message enqueue commit
atomically; the `outbox_worker` relays it to Kafka afterwards.

```python
from foundation.state import get_service
from foundation.resiliant.outbox import IOutboxService

async def credit_deposit(session, deposit):
    outbox = get_service(IOutboxService)

    async with session.begin():                 # ONE transaction
        await balances.credit(session, deposit.user_id, deposit.amount)
        await outbox.save_event(                 # staged in the same txn
            session,
            event=BalanceChangedEvent(
                event_id=deposit.tx_uuid,        # stable id → dedupe downstream
                user_id=deposit.user_id,
                amount=deposit.amount,
            ),
            channel="balance.changed",
            ordering_key=deposit.user_id,        # same user → same partition → ordered
        )
    # commit → both the credit and the outbox row are durable.
    # The outbox_worker publishes the row within one poll interval.
```

Raw payload (no event object):

```python
await outbox.save_raw_message(
    session, channel="orders", payload={"order_id": "o-1"}, event_type="OrderCreated"
)
```

**Config (`OUTBOX_*`):**

| Env | Default | Notes |
|---|---|---|
| `OUTBOX_POLL_STRATEGY` | `fixed` | `fixed` / `adaptive` / `notify` |
| `OUTBOX_FIXED_POLL_INTERVAL_MS` | `3000` | latency floor in `fixed` mode |
| `OUTBOX_BATCH_SIZE` | `100` | rows per claim |
| `OUTBOX_CONCURRENT_WORKERS` | `1` | raise for throughput; SKIP LOCKED keeps it safe |
| `OUTBOX_MAX_RETRIES` | `3` | then the row → `DEAD_LETTER` |
| `OUTBOX_NOTIFY_DSN` | – | asyncpg DSN to enable `LISTEN/NOTIFY` low-latency wakeups |

**Tips & traps**
- **Always set `ordering_key`** when order matters (per-user, per-account). No key = round-robin partitioning = reordered events.
- Use a **business-stable `event_id`** (the tx uuid, not a random one) so the consumer's idempotency guard can dedupe.
- For low latency without hammering the DB, use `poll_strategy=notify` + `wake()` after insert, instead of shrinking the poll interval.
- Publishing is *at-least-once* — the consumer still needs the idempotency guard (§3).

---

## 3. Idempotency — safe against duplicates

**Use when:** every consumer. Wrap the handler body in the guard; it records a
`(handler_name, event_id)` key with a race-safe `INSERT … ON CONFLICT`.

```python
from faststream.kafka import KafkaMessage
from messaging_faststream import messaging
from foundation.state import get_service
from foundation.resiliant.idempotency import IIdempotencyService

@messaging.subscriber("balance.changed")
async def on_balance_changed(event: BalanceChangedEvent, message: KafkaMessage):
    idem = get_service(IIdempotencyService)
    async with db.new_session() as session, session.begin():
        async with idem.guard(
            session,
            event_id=event.event_id,
            handler_name="RecalcRiskHandler",   # handler-scoped: other handlers still run
            event_type="BalanceChanged",
        ) as fresh:
            if fresh:                            # <-- you MUST branch on this
                await recalc_risk(session, event)
    # clean exit → key recorded (commits with your txn)
    # body raised  → key NOT recorded → message will be retried
```

**Tips & traps**
- The guard yields a **flag**, it can't skip your block implicitly — always
  `if fresh:`. (Or pass `raise_on_duplicate=True` for exception-style control.)
- The key is **handler-scoped**, so the same event can drive `RecalcRiskHandler`
  *and* `SendReceiptHandler` independently. Give each handler a distinct name.
- Keep the guard **inside the same transaction** as the work so the key and the
  effect commit together.
- Idempotency ≠ "handler runs exactly once" under a rare check-then-insert race;
  it means the *effect* is applied once. Your business logic must still tolerate
  a re-run (that's rule #2). Schedule `cleanup_expired()` off the hot path.

---

## 4. Dead Letter Queue — quarantine poison messages

**Use when:** a message has exhausted in-process retries and must be parked for
inspection/replay rather than blocking the partition.

```python
from foundation.resiliant.dlq import IDLQService

dlq = get_service(IDLQService)
try:
    await handle(event)
except Exception as exc:
    async with db.new_session() as session:
        await dlq.save_event(
            session,
            event_id=event.event_id,
            event_type="BalanceChanged",
            handler_name="RecalcRiskHandler",   # CRITICAL: used to re-dispatch on replay
            payload=event.as_dict(),
            original_error=repr(exc),
        )
```

**Ops / config (`DLQ_*`):** `list_pending`, `resolve`, `abandon`, `get_stats`
on `DLQService`; the DLQ poller retries with backoff up to `DLQ_MAX_RETRIES`
then `ABANDONED`.

**Tips & traps**
- Alert on **`dlq PENDING > 0`** — a healthy financial system has an empty DLQ.
- Always store `handler_name` and the full `payload`; replay needs both.
- Distinguish *retryable* (timeout, 503) from *non-retryable* (validation) —
  send the latter straight to DLQ, don't waste the retry budget.

---

## 5. Saga — durable multi-step workflows with rollback

**Use when:** a flow spans >1 local transaction and a later failure must undo
earlier steps (deposit: persist → credit → emit; withdrawal: reserve → sign →
broadcast). State is checkpointed to `saga_state` after every step, so a crash
resumes instead of losing progress.

```python
from foundation.resiliant.saga import SagaDefinition, SagaStep, SagaContext

async def persist_tx(ctx: SagaContext) -> None:
    ...                                          # ctx is a mutable JSON dict
async def credit_balance(ctx: SagaContext) -> None:
    ...
async def undo_credit(ctx: SagaContext) -> None: # compensation for credit_balance
    ...

deposit_saga = SagaDefinition(
    "deposit",
    [
        SagaStep("PERSIST_TX", persist_tx),
        SagaStep("CREDIT_BALANCE", credit_balance, compensation=undo_credit),
        SagaStep("EMIT_RISK_EVENT", emit_risk),
    ],
)

saga = ResiliantServiceFactory().get_saga_service()
instance = await saga.run(
    deposit_saga,
    context={"saga_key": f"{chain}:{tx_hash}", "amount": 100},  # saga_key = business anchor
    saga_id=deposit.tx_uuid,                                    # stable → safe to re-run
)
# If CREDIT_BALANCE succeeds but EMIT_RISK_EVENT fails, undo_credit runs, and the
# saga ends ABORTED. If a compensation itself fails → FAILED (needs a human).
```

**Signals** (inject external input, e.g. compliance approves KYC) — just a Kafka
handler that updates the saga and re-runs it. Grab the durable repository from
the builder:

```python
from resiliant import ResiliantServiceBuilder

repo = ResiliantServiceBuilder.build_saga_repository()   # SagaRepository
saga = await repo.get_by_key("kyc_onboarding", str(event.user_uuid))
if saga and saga.status is SagaStatus.RUNNING:
    saga.context["kyc_result"] = event.result
    await repo.save(saga)                        # next run() reads kyc_result
```

**Queries** (read live state for an API/dashboard):

```python
saga = await repo.get_by_key("deposit", f"{chain}:{tx_hash}")
return {"status": saga.status, "step": _current_step(saga)} if saga else {"status": "not_started"}
```

**Child workflows / fan-out:** the final step stages one outbox event per child
(`save_event(...)`, keyed per participant). Each child starts its own saga —
decoupled, independently retried.

**Tips & traps**
- **`saga_id` must be deterministic** (the tx/business id). Re-running with the
  same id is safe; a random id creates a duplicate saga.
- **Put `saga_key` in the context** — it's projected to an indexed column for
  signals/queries. One live saga per `(name, saga_key)`.
- Compensations should be **idempotent** too — they may run after a partial
  effect.
- Keep step **actions small and single-purpose**; each is a retry/resume
  boundary. Store progress in `ctx`, not in local variables.

---

## 6. Durable timers / Scheduler — "sleep" for seconds… or 30 days

**Use when:** you need something to happen *later* and survive restarts:
subscription billing, "wait up to 30 days for KYC", withdrawal
confirmation timeouts, nightly reconciliation. A row holds the wake-up time; the
`SchedulerPoller` (co-hosted in `outbox_worker`) fires it.

Three kinds — pick by recurrence:

```python
schedule = ResiliantServiceFactory().get_schedule_service()

# ONCE — a durable sleep. Commits with your business txn.
async with session.begin():
    await subscriptions.create(session, sub)
    await schedule.schedule_after(
        session,
        job_name="charge_subscription",
        delay_seconds=30 * 24 * 3600,            # 30 days
        channel="billing.charge",                # fire == publish to this topic
        payload={"subscription_id": sub.id},
    )

# INTERVAL — recurring timer (optionally capped).
await schedule.schedule_interval(
    session, job_name="heartbeat", interval_seconds=60, channel="ops.heartbeat"
)

# CRON — needs the croniter dep (already declared).
await schedule.schedule_cron(
    session, job_name="daily_reconciliation", cron_expr="0 2 * * *",  # 02:00 UTC
    channel="finance.reconcile",
)
```

**Two ways a job fires:**
- **channel set** → the payload is *published* to that topic (becomes a normal
  Kafka event other services consume). Prefer this — it keeps the scheduler
  decoupled.
- **no channel** → an in-process callback registered on the poller runs:

  ```python
  poller.register("rebuild_cache", rebuild_cache_handler)   # in worker wiring
  ```

Cancel: `await schedule.cancel(session, job_id)`.

**Config (`SCHEDULER_*`):** `SCHEDULER_FIXED_POLL_INTERVAL_MS` (default `30000`
— fine for day-scale timers), `SCHEDULER_MAX_RETRIES` (`3`),
`SCHEDULER_RETRY_BACKOFF_SECONDS` (`30`), `SCHEDULER_CLAIM_TIMEOUT_SECONDS`
(`300`, stale-claim recovery), `SCHEDULER_CONCURRENT_WORKERS` (`1`).

**Tips & traps**
- Polling precision = the poll interval. Business timers (minutes/hours/days) are
  fine; **don't** use this for sub-second/millisecond expiry.
- A failed fire retries `max_retries` times (backoff), then the job → `FAILED`
  (a recurring job stops — an operator re-enables it). Watch `FAILED` count.
- Store all state the handler needs in `payload`; the worker that fires it may
  be a different process than the one that scheduled it.
- Prefer `channel` dispatch: the fire is then itself idempotent/observable like
  any other event, and survives a scheduler restart mid-dispatch.

---

## 7. Resilient calls — guard flaky dependencies

**Use when:** calling anything external (chain RPC, KYC provider, payment
gateway). `ResilientExecutor` stacks timeout + circuit-breaker + bulkhead +
fallback from one config.

```python
from foundation.resiliant.resilient_call import ResilientExecutor
from foundation.resiliant.circuit_breaker import CircuitBreakerConfig
from foundation.resiliant.bulkhead import BulkheadConfig

kaspa_rpc = ResilientExecutor(
    "kaspa-rpc",
    timeout_seconds=5.0,                                   # cap each call
    circuit_breaker=CircuitBreakerConfig(failure_threshold=5,
                                         recovery_timeout_seconds=30.0),
    bulkhead=BulkheadConfig(max_concurrent=20),            # cap concurrency
)

tip = await kaspa_rpc.call(lambda: client.get_tip())

# with graceful degradation:
price = await kaspa_rpc.call(
    lambda: provider.fetch_price(sym),
    fallback=lambda exc: last_known_price(sym),            # used if the call fails
)
```

**Fleet-wide breaker** (one open breaker trips all replicas) — back it with
Redis:

```python
from store_redis import RedisStore, RedisCircuitBreakerRepository

cb_repo = RedisCircuitBreakerRepository(RedisStore.with_client(REDIS_URL))
executor = ResilientExecutor("kyc-provider",
                             circuit_breaker=CircuitBreakerConfig(),
                             cb_repository=cb_repo)
```

**Config defaults** — `CircuitBreakerConfig`: `failure_threshold=5`,
`recovery_timeout_seconds=30`, `half_open_max_calls=1`, `success_threshold=1`.
`BulkheadConfig`: `max_concurrent=10`, `acquire_timeout_seconds=None` (wait
forever). `TimeoutConfig`: `seconds=5`.

**Tips & traps**
- Composition order (outer→inner) is `fallback → circuit_breaker → bulkhead →
  timeout → fn`: an OPEN breaker fails fast *before* taking a bulkhead slot, and
  a timeout counts as a breaker failure. Rely on this; don't re-wrap manually.
- One executor **per dependency** (name it) — sharing a breaker across unrelated
  calls makes one flaky endpoint trip healthy ones.
- Set `acquire_timeout_seconds` on the bulkhead so callers fail fast instead of
  piling up when the dependency is saturated.
- For a *pure retry* (transient errors, no breaker), use the shared decorator
  instead: `from foundation.resiliant.retry import retry` → `@retry.decorator(name="start_producer")` (default: 30 attempts, exp backoff 1→60s, jitter).

---

## 8. The canonical handler pipeline

Compose the patterns in this order and every new flow inherits durability for
free:

```text
Kafka event
 └─ idempotency.guard(event_id)                 # §3 skip duplicates
     └─ saga.run(definition, saga_id=…)          # §5 durable, resumable
         └─ step:
             ├─ resilient_executor.call(...)      # §7 guard external I/O
             └─ outbox.save_event(...)            # §2 stage next/child events
     on step failure  → saga compensates / PENDING; a scheduled retry re-runs it  # §6
     on retries spent → dlq.save_event(...)                                        # §4
```

Everything from the guard down to `outbox.save_event` commits in **one Postgres
transaction** — that atomicity is the whole reason this stack beats stitching
Kafka + cron + ad-hoc retries by hand.

---

## 9. Visibility — "is anything stuck?"

```python
from resiliant import ResilienceVisibilityService

async with db.new_session() as session:
    snap = await ResilienceVisibilityService().snapshot(session)
# {'healthy': True,
#  'outbox':   {'pending': 2, 'dead_letter': 0, ...},
#  'dlq':      {'pending': 0, ...},
#  'saga':     {'running': 3, 'failed': 0, ...},
#  'schedule': {'scheduled': 5, 'failed': 0, ...}}
```

Expose it as `GET /health/resilience` (or from the worker health server) and
alert when `healthy` is false. Point Grafana at the same counts. In handlers,
stamp trace attributes so a stuck flow is one search away:

```python
from resiliant import set_resilience_attributes
set_resilience_attributes(saga_id=saga.id, saga_step=_current_step(saga),
                          event_id=event.event_id)
```

**Ad-hoc SQL** is always available too, e.g. sagas stuck retrying > 1h:

```sql
SELECT name, saga_key, current_step, last_error, updated_at
FROM   resiliant_saga_state
WHERE  status = 'running' AND updated_at < now() - interval '1 hour';
```

---

## 10. Versioning — deploy safely while flows are in flight

The pattern-stack equivalent of Temporal's `workflow.patched()`. Because saga
steps are looked up by **string name**:

- **Add** steps freely — in-flight sagas past the insertion point skip them.
- **Never rename/drop** a step name (or a column a persisted `context`/`steps`
  payload needs) while instances may be in flight. Migrations are
  **additive-only**.
- Gate behavioural changes behind a **settings flag**: new flows take the new
  branch, in-flight ones finish on the path they started; roll back by flipping
  the flag.
- Treat a scheduler **`job_name`** as a stable contract between producer and
  dispatcher/channel.

(The full policy lives in `libs/resiliant/README.md` — enforce it in review.)

---

## 11. Decision table — which pattern?

| Your problem | Reach for | Section |
|---|---|---|
| "DB write must reliably emit an event" | Outbox | §2 |
| "This event may arrive twice" | Idempotency guard | §3 |
| "Message keeps failing, don't block the partition" | DLQ | §4 |
| "Multi-step flow that must roll back on failure" | Saga | §5 |
| "Do X later / on a schedule / after a long wait" | Scheduler | §6 |
| "External call is slow or flaky" | ResilientExecutor | §7 |
| "Is the system healthy? where is it stuck?" | Visibility | §9 |
| "Deploy new flow logic without breaking running ones" | Versioning | §10 |

---

## 12. Local setup checklist

- `uv sync --all-packages --prerelease=allow` (installs `croniter` for CRON jobs).
- Migrate the resilience tables — `resiliant_outbox_events`, `_dlq_events`,
  `_processed_events`, **`_saga_state`, `_scheduled_jobs`** — via
  `uv run python -m db.migrations upgrade head` (see the db migration guide).
- Run the relay: `./start_outbox.sh` — this one process hosts **both** the
  outbox poller and the scheduler poller.
- Run consumers: `./start_worker.sh` (ews_worker) for the Kafka handlers.
- Fast, dependency-free unit examples of every pattern live in
  `libs/resiliant/tests/unit_local/` and `libs/foundation/tests/unit_local/`.
