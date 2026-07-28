# Resilience Patterns Reference — Finance Platform

> **Scope:** Patterns for building resilient, scalable, high fault-tolerant distributed
> systems in a financial context.  Grounded in this codebase's implementation but
> written as a reusable reference.
>
> **Implemented in:** `libs/core/src/core/saga/` + `libs/wallets/src/wallets/worker/sagas/`

---

## Table of Contents

1. [Why Finance Demands Extra Resilience](#1-why-finance-demands-extra-resilience)
2. [Pattern Overview Map](#2-pattern-overview-map)
3. [Saga Pattern](#3-saga-pattern)
4. [Transactional Outbox Pattern](#4-transactional-outbox-pattern)
5. [Idempotency Pattern](#5-idempotency-pattern)
6. [Retry with Exponential Back-off](#6-retry-with-exponential-back-off)
7. [Dead Letter Queue (DLQ)](#7-dead-letter-queue-dlq)
8. [Pessimistic Locking (SELECT FOR UPDATE SKIP LOCKED)](#8-pessimistic-locking-select-for-update-skip-locked)
9. [Compensation / Rollback](#9-compensation--rollback)
10. [At-Least-Once vs Exactly-Once Delivery](#10-at-least-once-vs-exactly-once-delivery)
11. [How the Patterns Compose](#11-how-the-patterns-compose)
12. [Failure Mode Matrix](#12-failure-mode-matrix)
13. [Implementation Notes for This Codebase](#13-implementation-notes-for-this-codebase)
14. [Extending to New Business Flows](#14-extending-to-new-business-flows)
15. [Glossary](#15-glossary)

---

## 1. Why Finance Demands Extra Resilience

Financial operations carry **asymmetric risk**: a bug that credits a user's balance twice
costs real money; a bug that forgets to credit costs trust and triggers support incidents.
Systems that are "usually correct" are not good enough.

| Risk | Consequence in finance |
|------|-----------------------|
| Duplicate event processing | Double credit/debit, duplicate email, double commission |
| Lost event (crash between steps) | Balance updated but user never notified; audit trail incomplete |
| Partial write (DB committed, Kafka not sent) | Downstream consumers miss state change; system divergence |
| Non-atomic multi-step flow | Money moved to step 2, step 3 fails — partial state permanently |
| No retry on transient failure | Valid transaction discarded silently; user sees missing deposit |

The patterns below solve each of these failure classes systematically, at the
infrastructure layer, so individual handlers do not need to re-implement them.

---

## 2. Pattern Overview Map

```
Incoming Event (Kafka)
        │
        ▼
┌───────────────────┐
│  Idempotency Gate │  — ProcessedEventRegistry
│  "Have I seen     │    Blocks duplicate processing before any work begins
│   this event_id?" │
└───────────────────┘
        │ (new event)
        ▼
┌───────────────────┐
│  Saga Runner      │  — SagaRunner.start() + advance()
│  Orchestrates the │    Breaks multi-step flow into individually retryable steps
│  multi-step flow  │    Holds state in PostgreSQL (saga_state table)
└───────────────────┘
        │
        ▼  (for each step)
┌───────────────────┐         ┌──────────────────────┐
│  Step Activity    │ success │  Outbox Writer       │
│  (pure DB work)   ├────────►│  Stages Kafka events │  — SagaOutboxOrm written
│                   │         │  in same transaction  │    atomically with state
└───────────────────┘         └──────────────────────┘
        │ failure
        ▼
┌───────────────────┐
│  Retry Back-off   │  — RETRY_DELAYS = [5s, 30s, 2m, 10m, 1h]
│  (saga_state.     │    Saga timer polls PENDING_RETRY sagas
│   retry_after)    │
└───────────────────┘
        │ (MAX_ATTEMPTS exceeded)
        ▼
┌───────────────────┐
│  Compensation /   │  — Registered compensation function per step
│  Rollback         │    Reverses completed steps in reverse order
└───────────────────┘
        │ (compensation also fails)
        ▼
┌───────────────────┐
│  Dead Letter      │  — FailedEventOrm (saga_failed_events table)
│  Queue (DLQ)      │    Alert + manual review / replay
└───────────────────┘

                             ↓ (independent process)
┌───────────────────┐
│  Outbox Consumer  │  — Faust timer, polls saga_outbox, publishes to Kafka
│  (saga timer)     │    SELECT FOR UPDATE SKIP LOCKED prevents double-publish
└───────────────────┘
```

---

## 3. Saga Pattern

### What it is

A **Saga** is a sequence of local database transactions, each owning one step of a
long-running business flow.  If a step fails, previously-completed steps are
undone by running **compensating transactions** in reverse.

It replaces a single distributed transaction (which requires 2-Phase-Commit and locks
many services) with a series of small, independently committable steps.

### Two styles

| Style | How coordination works | When to use |
|-------|----------------------|-------------|
| **Choreography** | Each service publishes an event; others react | Simple flows (≤3 steps), loose coupling |
| **Orchestration** | A single runner tells each service what to do next | Complex flows (>3 steps), easier debugging |

> This codebase uses **orchestration** implemented in `SagaRunner`.  The runner is
> the single source of truth for where in a flow a saga currently is.

### The four saga states

```
STARTED
  │
  ▼
IN_PROGRESS ──► (each step advance)
  │
  ├── success on all steps ──► COMPLETED ✓
  │
  ├── step fails, retries remain ──► PENDING_RETRY (retry after delay)
  │                                       │
  │                                       └──► IN_PROGRESS (after delay)
  │
  └── step fails, retries exhausted ──► COMPENSATING
                                             │
                                             ├── compensation OK ──► COMPENSATED
                                             └── compensation fails ──► FAILED (DLQ)
```

### Why it beats the old approach

| Old approach (flat EventProcessor) | Saga orchestration |
|------------------------------------|-------------------|
| 100+ handlers in a flat chain | Each flow isolated in its own folder |
| One failure silently drops the event | Retry schedule + DLQ |
| No audit trail of intermediate steps | `saga_state.current_step` always visible |
| No compensation logic | Registered per-step compensations |
| Re-reading entire handler chain per event | Saga jumps directly to its current step |

### Implementation

```python
# libs/core/src/core/saga/runner.py
runner = SagaRunner(
    saga_type="deposit",
    steps={
        "PERSIST_TRANSACTION": persist_transaction,
        "CREDIT_BALANCE":      credit_balance,
        "EMIT_RISK_EVENT":     emit_risk_recalculation,
    },
    compensations={
        "CREDIT_BALANCE": debit_balance,  # reverses the credit if later steps fail
    },
)

# Idempotent start (returns existing saga if saga_key already exists)
saga = await runner.start(saga_key="eth:mainnet:0xabc:0xaddr", first_step="PERSIST_TRANSACTION", payload={...}, session=session)

# Advance through steps (call in a loop until terminal state)
saga = await runner.advance(saga.uuid, session)
```

---

## 4. Transactional Outbox Pattern

### The problem it solves

Publishing a Kafka message and committing a database record can *never* be
made atomic using a simple "write DB, then send Kafka" approach:

```
# DANGEROUS — dual-write
await session.commit()                 # ← DB committed
await messaging_service.send(event)   # ← crash here → DB updated, Kafka silent
```

After a crash the DB shows the new state but no downstream consumers were notified.
This causes **system divergence** — harder to detect and fix than an outright error.

### The solution

Write the Kafka payload **into a database table** (`saga_outbox`) in the **same
transaction** as the business state change.  A separate background process
(the outbox consumer) reads `PENDING` rows and publishes them to Kafka.

```
┌────────────────────────────────────┐
│  Single DB transaction             │
│                                    │
│  UPDATE saga_state SET status=...  │
│  INSERT INTO saga_outbox (...)     │  ← Kafka payload stored here
└────────────────────────────────────┘
              ↓ commit
              ↓ (background, eventually)
┌────────────────────────────────────┐
│  Outbox Consumer (Faust timer)     │
│  SELECT ... FOR UPDATE SKIP LOCKED │
│  → messaging_service.send(...)     │
│  → UPDATE saga_outbox SET SENT     │
└────────────────────────────────────┘
```

### Key properties

- **Atomicity guaranteed:** Either both the state change and the outbox row are visible,
  or neither is (standard DB transaction semantics).
- **At-least-once delivery:** If the consumer crashes after publishing but before marking
  SENT, it will re-publish on restart.  Consumers must be idempotent (they are — see §5).
- **Ordering:** Messages are published in `created_at` order within each saga.
- **No new infrastructure:** The outbox is just a PostgreSQL table; no CDC connector or
  Debezium required.

### Implementation

```python
# libs/core/src/core/saga/outbox.py
class OutboxConsumer:
    async def publish_pending(self, session: AsyncSession) -> int:
        rows = await session.execute(
            select(SagaOutboxOrm)
            .where(SagaOutboxOrm.status == OutboxStatus.PENDING)
            .order_by(SagaOutboxOrm.created_at)
            .limit(100)
            .with_for_update(skip_locked=True)   # ← prevents double-publish
        )
        for row in rows:
            await messaging_service.send(row.topic, row.payload, key=row.message_key)
            row.status = OutboxStatus.SENT
```

---

## 5. Idempotency Pattern

### The problem it solves

Kafka's `AT_LEAST_ONCE` guarantee means a consumer may receive the same message
more than once after a restart or rebalance.  Without protection:

- A deposit confirmation is processed twice → balance credited twice
- A confirmation email is sent twice → user receives duplicate notification
- A blockchain transaction is broadcast twice → funds double-spent or TX rejected

### The solution

Before doing any work, check whether a deterministic **event ID** has already been
recorded in a `processed_events` table.  If yes, skip.  Record the ID atomically
with the business operation using `ON CONFLICT DO NOTHING`.

```python
# libs/core/src/core/saga/idempotency.py
registry = ProcessedEventRegistry(session)

# 1. Check before doing any work
if await registry.is_processed(event_id):
    return  # already handled — safe to skip

# 2. Do business work...

# 3. Mark as processed atomically with the commit
await registry.mark_processed(event_id, event_type, saga_id=saga.uuid)
# ← uses INSERT ... ON CONFLICT DO NOTHING (race-safe)
```

### Designing idempotency keys

An idempotency key must:
- Be **deterministic** from the event content (so re-delivered events produce the same key)
- Be **unique** per logical operation (so different events produce different keys)
- Be **scoped** to the operation type

| Flow | Suggested key format |
|------|---------------------|
| Deposit | `deposit:{blockchain}:{network}:{tx_hash}:{address_uuid}` |
| Withdrawal | `withdrawal:{tx_representation_uuid}` |
| Commission | `commission:{trade_uuid}:{participant_uuid}` |
| Email | `email:{template}:{user_uuid}:{ref_id}` |

### Natural idempotency in step functions

Individual step functions should also be idempotent:

```python
# CORRECT: check before insert — safe to call multiple times
existing = await session.scalar(select(TxOrm).where(TxOrm.uuid == tx_uuid))
if existing is None:
    session.add(TxOrm(uuid=tx_uuid, ...))
```

---

## 6. Retry with Exponential Back-off

### Why exponential back-off matters

Linear retry (retry every 1 second) causes **retry storms**: all workers hammer
a database or external service that is already struggling, making recovery slower.

Exponential back-off spaces retries out so the system naturally recovers when
the upstream issue resolves.

### Schedule used in this codebase

| Attempt | Delay before retry |
|---------|-------------------|
| 1st | 5 seconds |
| 2nd | 30 seconds |
| 3rd | 2 minutes |
| 4th | 10 minutes |
| 5th | 1 hour |
| 6th (final) | → compensation → DLQ |

```python
# libs/core/src/core/saga/runner.py
RETRY_DELAYS_SECONDS = [5, 30, 120, 600, 3_600]
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS) + 1  # 6

# After each failure:
delay = RETRY_DELAYS_SECONDS[min(saga.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)]
saga.retry_after = datetime.now(utc) + timedelta(seconds=delay)
saga.status = SagaStatus.PENDING_RETRY
```

### Two error categories

| Type | Action |
|------|--------|
| **Retryable** (network timeout, DB unavailable, external API 5xx) | Apply back-off, retry up to MAX_ATTEMPTS |
| **Non-retryable** (`NonRetryableError`) (bad payload, address not found) | Skip retries, compensate immediately |

```python
from core.saga.exceptions import NonRetryableError

async def my_step(payload, session):
    if not payload.get("tx_uuid"):
        raise NonRetryableError("Missing tx_uuid — cannot proceed")  # ← no retry
    ...
```

### Who executes retries

A Faust timer (`on_leader=True`) polls for sagas in `PENDING_RETRY` state whose
`retry_after` has passed, and calls `runner.advance()` on each.  This keeps retry
logic completely separate from event ingestion.

---

## 7. Dead Letter Queue (DLQ)

### What it is

When a saga exhausts all retry attempts AND its compensation also fails, the event
is written to `saga_failed_events` (the DLQ table).  This is the last safety net
before a failure requires manual intervention.

### What to store in the DLQ

```python
FailedEventOrm(
    saga_type    = "deposit",
    event_id     = "deposit:eth:mainnet:0xabc:0xaddr",
    event_type   = "CREDIT_BALANCE",         # which step failed
    event_payload = {...},                    # original trigger payload
    error_message = "...",                   # last error text
    retry_count   = 6,                       # how many times it was attempted
)
```

### Operational responses

| Scenario | Action |
|----------|--------|
| Transient infrastructure issue (DB was down) | Fix infra, replay via `event_payload` |
| Bug in step code | Deploy fix, replay via `event_payload` |
| Invalid data (wrong enum value, missing field) | Fix data, replay or close manually |
| Irreversible (external blockchain TX already broadcast) | Manual reconciliation |

### Monitoring

Alert immediately when `saga_failed_events` row count increases.  This table
should receive zero events under normal operation.

```sql
-- Health check query
SELECT saga_type, event_type, COUNT(*) AS failures, MAX(created_at) AS last_failure
FROM {prefix}saga_failed_events
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2
ORDER BY 3 DESC;
```

---

## 8. Pessimistic Locking (SELECT FOR UPDATE SKIP LOCKED)

### The problem

With multiple Faust worker processes running, two workers can read the same
saga row simultaneously and both attempt to advance it — causing duplicate step
execution.

### The solution

`SELECT … FOR UPDATE SKIP LOCKED`: a row-level lock that:
- **FOR UPDATE** — blocks other transactions from modifying the same row
- **SKIP LOCKED** — other workers skip locked rows instead of waiting (no pile-up)

```python
# SagaRunner.advance() — inside a transaction
result = await session.execute(
    select(SagaStateOrm)
    .where(SagaStateOrm.uuid == saga_id)
    .with_for_update(skip_locked=True)
)
saga = result.scalar_one_or_none()
if saga is None:
    return None  # another worker holds the lock — skip silently
```

The same pattern is used by the outbox consumer to prevent duplicate Kafka publishes.

### Why this works (and when it breaks)

- Works correctly as long as all workers use the **same PostgreSQL instance**.
- Does NOT work across multiple isolated databases.
- Lock is held only for the duration of a single database transaction (milliseconds),
  so it does not cause long-lived contention.

---

## 9. Compensation / Rollback

### Why 2-Phase-Commit is not used

2PC requires all participants to hold locks while the coordinator deliberates.
In a distributed system over Kafka + multiple services this is either impossible
or causes unacceptable latency.

### The saga approach to rollback

Each step that modifies state registers a **compensation function** that undoes
the change.  If a later step fails, the runner calls compensations in reverse order.

```
Step 1: PERSIST_TRANSACTION  →  compensation: delete_transaction
Step 2: CREDIT_BALANCE       →  compensation: debit_balance        ← called on failure
Step 3: EMIT_RISK_EVENT      →  (no compensation — Kafka is fire-and-forget)
```

### Compensation design rules

1. **Compensations must be idempotent** — they may be called more than once.
2. **Compensations must not fail on missing data** — the original step may have
   partially succeeded or not run at all.
3. **Some operations cannot be compensated** (e.g. an email already sent, a
   blockchain TX already broadcast).  Design these as the *last* step in the
   sequence so earlier steps can still be rolled back.
4. **Never compensate a compensation** — compensations are terminal.

```python
# Example: safe, idempotent compensation
async def debit_balance(payload, session):
    address = await session.scalar(...)
    if address is None:
        return  # silently skip — address may have been rolled back already
    token = payload["token"].lower()
    current = address.clean_balances.get(token, 0)
    address.clean_balances[token] = max(0, current - payload["amount"])  # clamp at 0
```

---

## 10. At-Least-Once vs Exactly-Once Delivery

### Delivery guarantees

| Guarantee | What it means | Who provides it |
|-----------|---------------|-----------------|
| At-most-once | Message may be lost, never duplicated | Unreliable — use only when loss is acceptable |
| At-least-once | Message delivered ≥1 times; may duplicate | Kafka default; this codebase's setting |
| Exactly-once | Message delivered exactly once | Kafka transactions (Faust EOS) OR idempotent consumers |

### Why exactly-once at the broker level is not enough

Even with Kafka's `EXACTLY_ONCE` processing guarantee, a consumer crash between
the DB commit and the Kafka offset commit can cause re-delivery.  The only
reliable solution is **idempotent consumers**: check the `processed_events` table
before acting.

### The formula for this codebase

```
At-Least-Once (Faust setting)
  + Idempotency table (ProcessedEventRegistry)
  + Saga state machine (SagaStateOrm)
  = Effectively exactly-once business semantics
```

---

## 11. How the Patterns Compose

The patterns are designed to work as **interlocking layers**, each closing the gaps
left by the others:

```
Layer 1: Delivery guarantee (Kafka AT_LEAST_ONCE)
  └─ Gap: duplicate events
       └─ Closed by: Idempotency gate (§5)

Layer 2: Multi-step execution (Saga orchestration)
  └─ Gap: partial state after crash mid-flow
       └─ Closed by: Saga state persisted in DB (§3)

Layer 3: Saga step execution
  └─ Gap: transient external failure (DB, API)
       └─ Closed by: Retry with back-off (§6)

Layer 4: Event publishing after step
  └─ Gap: crash between DB commit and Kafka send
       └─ Closed by: Transactional Outbox (§4)

Layer 5: Multi-worker concurrency
  └─ Gap: two workers process same saga simultaneously
       └─ Closed by: SELECT FOR UPDATE SKIP LOCKED (§8)

Layer 6: Permanent failure after max retries
  └─ Gap: data left in inconsistent state
       └─ Closed by: Compensation (§9) + DLQ (§7)
```

No single pattern closes all gaps.  All six layers must be present for a finance
system to be fully resilient.

---

## 12. Failure Mode Matrix

| Failure scenario | Pattern that handles it | Recovery |
|------------------|------------------------|----------|
| Kafka delivers event twice | Idempotency gate | Automatic (skip duplicate) |
| Process crashes mid-saga | Saga state in DB | Automatic (saga timer resumes) |
| DB connection timeout in step | Retry + back-off | Automatic (after delay) |
| External API 5xx | Retry + back-off | Automatic (after delay) |
| Invalid payload (bad data) | `NonRetryableError` → DLQ | Manual (fix + replay) |
| Address not found | `NonRetryableError` → DLQ | Manual (investigate) |
| Kafka publish fails after DB commit | Outbox consumer retry | Automatic |
| Two workers pick same saga | SKIP LOCKED | Automatic (one skips) |
| Step fails 6 times | Compensation → DLQ | Manual (after alert) |
| Compensation also fails | FAILED + DLQ | Manual (alert + reconcile) |
| Worker cold restart | Saga timer resumes PENDING_RETRY | Automatic |

---

## 13. Implementation Notes for This Codebase

### Table structure

Four tables are created in PostgreSQL (all prefixed with `TENANT_PREFIX`):

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `{prefix}saga_state` | One row per saga instance | `saga_type`, `saga_key`, `status`, `current_step`, `payload`, `retry_after` |
| `{prefix}saga_outbox` | Kafka messages staged atomically | `topic`, `message_key`, `payload`, `status` |
| `{prefix}saga_processed_events` | Idempotency log | `event_id` (unique), `event_type` |
| `{prefix}saga_failed_events` | DLQ | `event_payload`, `error_message`, `retry_count` |

### DB migration

Add all four tables via an Alembic migration (or raw SQL) before deploying the code.
The `UniqueConstraint('saga_type', 'saga_key')` on `saga_state` is critical — it
enforces single-instance-per-flow at the database level.

### Session management

The `SagaRunner` accepts an explicit `AsyncSession` parameter rather than using the
`@db_session_async` decorator.  This is intentional:

- `SELECT FOR UPDATE` requires an explicit, non-auto-committed session
- The caller controls when the transaction commits (ensures atomicity across start + advance)
- The deposit trigger wraps everything in `db.get_current_session_generator()`

### Outbox consumer timer

Add to `agents.py` (inside `if settings.WORKER_RUN_NON_OHLCV_TASKS:`):

```python
_outbox_consumer = OutboxConsumer(messaging_service=factory.get_messaging_service())

@faust_app.timer(interval=2.0, on_leader=True)
async def publish_saga_outbox():
    async with db.get_current_session_generator() as session:
        sent = await _outbox_consumer.publish_pending(session)
        if sent:
            logger.info("Outbox: published %d messages", sent)
```

### Saga retry poller timer

```python
@faust_app.timer(interval=10.0, on_leader=True)
async def retry_pending_sagas():
    async with db.get_current_session_generator() as session:
        now = datetime.now(tz=timezone.utc)
        pending = await session.scalars(
            select(SagaStateOrm)
            .where(SagaStateOrm.status == SagaStatus.PENDING_RETRY)
            .where(SagaStateOrm.retry_after <= now)
            .limit(50)
        )
        for saga_state in pending.all():
            runner = _runner_for(saga_state.saga_type)  # registry of runners
            await runner.advance(saga_state.uuid, session)
```

---

## 14. Extending to New Business Flows

Adding a new saga (e.g. `withdrawal`) follows this checklist:

```
libs/wallets/src/wallets/worker/sagas/withdrawal/
  __init__.py
  saga.py       ← SAGA_TYPE, step constants, make_runner()
  activities.py ← one async function per step + compensation functions
  trigger.py    ← DepositTrigger-equivalent for withdrawal
```

**Step-by-step:**

1. **Define steps** in `saga.py` as string constants and map each to an activity function.
2. **Write activities** in `activities.py`.  Each function:
   - Accepts `(payload: dict, session: AsyncSession) → StepResult`
   - Is idempotent (check-before-insert)
   - Raises `NonRetryableError` for permanent failures
   - Returns `StepResult(next_step=NEXT_STEP_NAME, outbox_events=[...])`
   - Returns `StepResult(next_step=None)` to mark completion
3. **Register compensations** for any step that modifies money/balance.
4. **Write a trigger** that builds the payload dict, creates the saga, and advances it.
5. **Route events** from the appropriate Faust agent to the trigger.
6. **Register the runner** in the retry poller's `_runner_for()` registry.

### What NOT to do

- Do not call `messaging_service.send()` directly inside a step — use `StepResult.outbox_events`
- Do not use `@db_session_async` inside a step function — the session comes from the runner
- Do not share mutable state between steps — all state lives in `saga.payload`
- Do not put compensation logic at the end of the step — register it separately so the
  runner can call it even if registration happens inside a different code path

---

## 15. Glossary

| Term | Definition |
|------|-----------|
| **Saga** | A sequence of local transactions that collectively implement one distributed business transaction |
| **Orchestration** | A central coordinator (runner) controls step sequencing |
| **Choreography** | Each service reacts to events published by the previous service |
| **Idempotency** | Property of an operation: calling it N times has the same effect as calling it once |
| **Idempotency key** | A deterministic unique identifier for a logical operation |
| **Transactional Outbox** | A DB table used to stage Kafka messages inside a transaction before publishing |
| **Compensation** | A business-level undo operation that reverses the effect of a saga step |
| **DLQ (Dead Letter Queue)** | Storage for events that failed all retry attempts, awaiting manual review |
| **SELECT FOR UPDATE SKIP LOCKED** | A PostgreSQL construct that locks a row for the current transaction and skips rows already locked |
| **AT_LEAST_ONCE** | Kafka delivery guarantee: a message is delivered at least once but may be duplicated |
| **Dual write** | Anti-pattern: writing to two independent systems (DB + Kafka) without atomicity |
| **Back-off** | Increasing delay between retry attempts to reduce pressure on a struggling system |
| **Retry storm** | Cascading overload caused by many workers retrying rapidly in parallel |
| **Step function / Activity** | A single atomic unit of work within a saga; corresponds to one DB transaction |
| **Saga key** | Business-level unique identifier for a saga instance (e.g. `{blockchain}:{txhash}:{address}`) |
| **Terminal state** | Final saga status: COMPLETED, COMPENSATED, or FAILED — no further transitions |
