# Temporal Features vs Alternative Software Patterns
## Complete 1-to-1 Comparison for the Floin Platform

> **Purpose:** Temporal is a durable execution platform that bundles many capabilities
> into one system. This document maps every Temporal feature to the equivalent
> combination of patterns already described in this folder's other documents, so the
> team can make an informed build-vs-adopt decision per feature.
>
> **Source documents:**
> - `temporal-overview.md` — Temporal feature catalogue
> - `temporal-python-examples.md` — Python SDK code for 6 use cases
> - `saga-implementation-plan.md` — SagaRunner implementation
> - `resilience-patterns-reference.md` — Pattern theory and composition
> - `lightweight-resilience-proposal.md` — Decorator patterns
> - `popular-microservice-patterns.md` — Full pattern catalogue
> - `system-improvement-master-plan.md` — Migration phases

---

## Quick Verdict

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Temporal = message queue + DB state machine + cron + retry + UI        │
│             all bundled into one managed service                        │
│                                                                         │
│  Pattern stack = the same capabilities, assembled from components       │
│                  you already own: PostgreSQL + Kafka + Python           │
└─────────────────────────────────────────────────────────────────────────┘
```

| | Temporal | Pattern stack |
|---|---|---|
| New infrastructure required | Yes — Temporal server cluster | No — PostgreSQL + Kafka already deployed |
| Operational burden | High — new service to run, scale, monitor, upgrade | Low — patterns are code in existing services |
| Learning curve | High — new SDK, new execution model | Low — same Python + SQLAlchemy patterns |
| Debuggability | High — Temporal UI shows all workflow state | Medium — DB queries on saga_state + distributed tracing |
| Feature completeness | Full — all features built-in | Full — same features, assembled per-pattern |
| Risk of adopting | Medium — new external dependency | Low — additive code on proven stack |
| Best for | Greenfield projects or flows with durable sleep > 1 hour | Existing systems, financial platforms, DB-first architectures |

---

## Feature-by-Feature Comparison

---

### Feature 1 — Durable Workflows (Survive Crashes and Resume)

#### What Temporal does

A workflow function stores its execution history in the Temporal server. When the
worker crashes mid-function, it restarts and **replays the history** to reconstruct
the in-memory state. The function resumes from the last successfully completed
activity — no work is duplicated.

```python
# Temporal: crash mid-function → resumes here automatically
@workflow.defn
class DepositWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> str:
        await workflow.execute_activity(persist_transaction, payload)   # step 1
        await workflow.execute_activity(credit_balance, payload)        # step 2 ← crashed here?
        await workflow.execute_activity(emit_risk_event, payload)       # step 3
        return "done"
```

#### Pattern equivalent

**`SagaRunner` + `saga_state` table in PostgreSQL**

State is not stored in Temporal's server — it is stored in a `saga_state` row.
On crash, Kafka re-delivers the event (AT_LEAST_ONCE). The `SagaRunner` reads
`current_step` from the DB and jumps directly to the next unfinished step.

```python
# Pattern equivalent: saga_state.current_step is the "resume pointer"
saga = await runner.start(saga_key=deposit_key, first_step="PERSIST_TRANSACTION", ...)

while saga.status not in TERMINAL_STATES:
    saga = await runner.advance(saga.uuid, session)
    # advance() reads saga_state.current_step, runs only that step
    # if crash here → Kafka re-delivers → advance() resumes from current_step
```

```
saga_state row:
  saga_type    = "deposit"
  saga_key     = "eth:mainnet:0xabc:0xaddr"
  current_step = "CREDIT_BALANCE"          ← resume pointer
  status       = "IN_PROGRESS"
  payload      = { ... }
```

#### Comparison

| Dimension | Temporal | SagaRunner |
|-----------|---------|-----------|
| Resume mechanism | Event history replay | Read `current_step` from DB |
| Where state lives | Temporal server (Cassandra or PostgreSQL internally) | Your PostgreSQL (`saga_state`) |
| Crash guarantee | Automatic replay | Kafka AT_LEAST_ONCE + idempotency |
| Duplicate prevention | History ensures step runs once | `@idempotent` on each activity |
| Visibility | Temporal UI | `SELECT * FROM saga_state` |
| Complexity | Framework handles it | 80 lines of `runner.py` |

---

### Feature 2 — Activities with Automatic Retry and Timeout

#### What Temporal does

Each activity (unit of work) has a declarative retry policy. Temporal retries
the activity independently of the workflow, tracking attempt count and back-off
schedule automatically.

```python
# Temporal: retry policy is declarative, tracked by server
await workflow.execute_activity(
    credit_balance,
    args=[payload],
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy=workflow.RetryPolicy(
        maximum_attempts=5,
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,         # exponential back-off
        non_retryable_error_types=["ValueError"],
    ),
)
```

#### Pattern equivalent

**`@retryable` decorator + `saga_state.retry_after` + `saga_state.attempts`**

For **simple single-transaction handlers**, the `@retryable` decorator wraps the
handler's `run()` method and retries in-process with exponential back-off + jitter.

For **saga steps**, the `SagaRunner` stores `retry_after` and `attempts` in the
`saga_state` row. The saga retry poller picks up `PENDING_RETRY` sagas after the
back-off period and re-runs `advance()`.

```python
# Simple handler: @retryable decorator
class CreditBalanceHandler(EventHandler):
    @idempotent(lambda e: f"credit:{e.tx_uuid}")
    @retryable(
        delays=(1, 5, 30, 120, 600),          # exponential back-off in seconds
        non_retryable=(ValueError, KeyError),  # no retry for logic errors
    )
    async def run(self, event, session=None):
        ...

# Saga step: retry schedule in saga_state
RETRY_DELAYS = [5, 30, 120, 600, 3_600]   # same schedule, stored in DB

# saga_state after failure:
#   attempts   = 2
#   retry_after = now + 120s      ← polled by saga retry timer
#   status     = "PENDING_RETRY"
```

```python
# Saga retry poller (agents.py timer — replaces Temporal's server-side scheduler)
@faust_app.timer(interval=10.0, on_leader=True)
async def retry_pending_sagas():
    now = datetime.now(tz=timezone.utc)
    async with db.get_current_session_generator() as session:
        pending = await session.scalars(
            select(SagaStateOrm)
            .where(SagaStateOrm.status == SagaStatus.PENDING_RETRY)
            .where(SagaStateOrm.retry_after <= now)
            .limit(50)
            .with_for_update(skip_locked=True)   # prevents double-retry
        )
        for saga in pending:
            await _runners[saga.saga_type].advance(saga.uuid, session)
```

#### Comparison

| Dimension | Temporal | @retryable + SagaRunner |
|-----------|---------|------------------------|
| Retry tracking | Temporal server | `saga_state.attempts` + `retry_after` |
| Back-off schedule | Declarative `RetryPolicy` | `RETRY_DELAYS` list |
| Jitter | Built-in | `random.uniform(0, base_delay)` |
| Per-step timeout | `start_to_close_timeout` | `asyncio.wait_for(step(), timeout=N)` |
| Non-retryable errors | `non_retryable_error_types` | `NonRetryableError` exception class |
| Retry visibility | Temporal UI | `WHERE status = 'PENDING_RETRY'` SQL |

---

### Feature 3 — Durable Timers (Sleep for Days or Years)

#### What Temporal does

`workflow.sleep(timedelta(days=30))` blocks the workflow for exactly 30 days
without consuming a thread or requiring a cron job. The workflow resumes
automatically after the delay. The server persists the wake-up time.

```python
# Temporal: durable sleep — survives all worker restarts in between
@workflow.defn
class SubscriptionBillingWorkflow:
    @workflow.run
    async def run(self, user_id: str, amount: float):
        while True:
            await asyncio.sleep(timedelta(days=30).total_seconds())  # durable
            await workflow.execute_activity(charge_subscription, args=[user_id, amount])
```

#### Pattern equivalent

**DB-persisted `scheduled_at` column + polling timer**

Store the "wake at" timestamp in the database. A polling timer (Faust timer or
APScheduler) queries for rows where `scheduled_at <= now()` and processes them.

```python
# DB row stores the wake-up time — survives all restarts
class SubscriptionOrm(BaseModel):
    user_uuid     : UUID
    monthly_amount: Decimal
    next_billing_at: datetime      # ← the durable timer
    status        : str            # ACTIVE / CANCELLED / FAILED

# Polling timer (every 60 seconds is sufficient for day-scale timers)
@faust_app.timer(interval=60.0, on_leader=True)
async def billing_poller():
    now = datetime.now(tz=timezone.utc)
    async with db.get_current_session_generator() as session:
        due = await session.scalars(
            select(SubscriptionOrm)
            .where(SubscriptionOrm.next_billing_at <= now)
            .where(SubscriptionOrm.status == "ACTIVE")
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        for sub in due:
            await charge_subscription(sub, session)
            sub.next_billing_at = now + timedelta(days=30)   # advance timer
```

For the KYC "wait up to 30 days" use case, the saga `saga_state` row with a
`retry_after` in the distant future serves the same role — the saga is
`PENDING_RETRY` until the KYC signal arrives (see Feature 4 below).

#### Comparison

| Dimension | Temporal | DB polling timer |
|-----------|---------|-----------------|
| Timer durability | Temporal server persists wake-up | DB row persists `next_billing_at` |
| Precision | Sub-second | Polling interval (1–60s for business timers) |
| Long timers (days/months) | Native — no resource cost | Same — DB row costs ~100 bytes |
| Timer cancellation | `workflow.cancel()` | `UPDATE SET status = 'CANCELLED'` |
| Multiple timers per entity | Multiple `sleep()` calls | Multiple timestamp columns or a `timers` table |
| Infrastructure | Temporal server | PostgreSQL (already deployed) |

> **When the pattern is NOT enough:** If you need sub-second precision durable
> timers at high volume (e.g. real-time order book expiry at millisecond granularity),
> Temporal's server-side timer wheel is superior. For all business-level timers
> (billing cycles, KYC waits, withdrawal confirmations), DB polling is sufficient.

---

### Feature 4 — Signals and Queries (External Input to a Running Flow)

#### What Temporal does

**Signals** inject data into a running workflow from outside (e.g. compliance team
approves KYC). **Queries** read the current state of a running workflow without
interrupting it.

```python
# Temporal: signal received → workflow unblocks
@workflow.defn
class KYCOnboardingWorkflow:
    def __init__(self):
        self._kyc_result = None

    @workflow.signal
    async def kyc_decision(self, result: str):
        self._kyc_result = result           # ← external event injected here

    @workflow.query
    def get_status(self) -> str:
        return self._kyc_result or "pending"

    @workflow.run
    async def run(self, user_id: str):
        await workflow.wait_condition(      # ← blocks until signal arrives
            lambda: self._kyc_result is not None,
            timeout=timedelta(days=30),
        )
```

#### Pattern equivalent

**Signals → Kafka event to the same topic + `saga_state` row update**
**Queries → Direct DB read of `saga_state`**

```python
# SIGNAL equivalent: compliance system sends a Kafka event
# The saga handler receives it, validates, and advances the saga

class KYCDecisionHandler(EventHandler):
    @idempotent(lambda e: f"kyc_decision:{e.kyc_request_uuid}")
    async def run(self, event: KYCDecisionEvent, session=None):
        saga = await session.scalar(
            select(SagaStateOrm)
            .where(SagaStateOrm.saga_type == "kyc_onboarding")
            .where(SagaStateOrm.saga_key == str(event.user_uuid))
            .with_for_update()
        )
        if not saga or saga.status in TERMINAL_STATES:
            return

        # Inject the signal data into the saga payload
        saga.payload["kyc_result"] = event.result
        saga.status = SagaStatus.IN_PROGRESS   # unblock the saga

        # advance() on next poll will read kyc_result from payload
        # and run the correct branch (activate or reject)
```

```python
# QUERY equivalent: read saga_state directly
async def get_kyc_status(user_uuid: UUID, session: AsyncSession) -> str:
    saga = await session.scalar(
        select(SagaStateOrm)
        .where(SagaStateOrm.saga_type == "kyc_onboarding")
        .where(SagaStateOrm.saga_key == str(user_uuid))
    )
    if not saga:
        return "not_started"
    return saga.status   # IN_PROGRESS / COMPLETED / FAILED / PENDING_RETRY
```

#### Comparison

| Dimension | Temporal (Signal) | Kafka event → saga payload update |
|-----------|-------------------|----------------------------------|
| Delivery mechanism | Temporal SDK client call | Kafka event on existing topic |
| Durability | Stored in Temporal server | Stored in `saga_state.payload` |
| Ordering guarantee | Signal ordered per workflow | Kafka partition ordering |
| Wait semantics | `wait_condition()` — blocks in code | Saga stays `IN_PROGRESS`; poll advances it |

| Dimension | Temporal (Query) | DB SELECT on saga_state |
|-----------|-----------------|------------------------|
| Real-time | Yes | Yes (no caching layer needed) |
| Historical | Yes — via Temporal visibility | Yes — `saga_state` is persistent |
| API exposure | Temporal SDK client | Any REST endpoint querying the DB |

---

### Feature 5 — Child Workflows (Composing Flows)

#### What Temporal does

A parent workflow can spawn child workflows. The parent waits for children to
complete (or runs them in parallel with `asyncio.gather`). Each child has its
own retry policy, timeout, and state.

```python
# Temporal: parent spawns children
@workflow.defn
class CommissionSettlementWorkflow:
    @workflow.run
    async def run(self, trade_uuid: str, participants: list[str]):
        # Pay all participants in parallel — each has its own retry
        await asyncio.gather(*[
            workflow.execute_child_workflow(PayParticipantWorkflow.run, p)
            for p in participants
        ])
```

#### Pattern equivalent

**Parent saga kicks off child sagas via the outbox (deferred events)**

The parent saga's final step writes one `stage_deferred()` event per participant.
Each event triggers an independent child saga, with its own `saga_state` row,
idempotency, and retry schedule.

```python
# Parent saga — final step stages child events atomically
async def emit_commission_events(saga_id, payload, session):
    for participant_uuid in payload["participants"]:
        stage_deferred(
            topic=SharedTopics.COMMISSION_EVENT,
            payload={
                "event_type": "PAY_PARTICIPANT",
                "participant_uuid": participant_uuid,
                "trade_uuid": payload["trade_uuid"],
                "amount": payload["commission_split"][participant_uuid],
            },
            key=participant_uuid,          # routes to same partition for same participant
        )
    return StepResult(next_step=None)      # parent saga → COMPLETED

# Each child event triggers its own independent saga
class PayParticipantTrigger:
    async def handle(self, event: CommissionEvent, session):
        runner = pay_participant_make_runner()
        saga_key = f"commission:{event.trade_uuid}:{event.participant_uuid}"
        saga = await runner.start(saga_key=saga_key, ...)
        while saga.status not in TERMINAL_STATES:
            saga = await runner.advance(saga.uuid, session)
```

#### Comparison

| Dimension | Temporal child workflows | Child saga via outbox event |
|-----------|--------------------------|----------------------------|
| Parent-child relationship | Explicit in Temporal — parent waits | Decoupled — parent emits event, child runs independently |
| Parallel execution | `asyncio.gather(child_workflows)` | All child events in outbox, consumed in parallel by multiple workers |
| Failure isolation | Child failure ≠ parent failure (configurable) | Child saga failure → child DLQ; parent already COMPLETED |
| Visibility | Temporal UI shows parent-child tree | Query `saga_state WHERE saga_key LIKE 'commission:trade_uuid:%'` |

---

### Feature 6 — Schedules and Cron Jobs

#### What Temporal does

Temporal Schedules run a workflow on a recurring interval or cron expression.
Handles timezone offsets, backfills missed runs, and tracks execution history.

```python
# Temporal: create a schedule
await client.create_schedule(
    "daily-reconciliation",
    Schedule(
        action=ScheduleActionStartWorkflow(ReconciliationWorkflow.run, task_queue="finance"),
        spec=ScheduleSpec(cron_expressions=["0 2 * * *"]),   # 2am daily
    ),
)
```

#### Pattern equivalent

**Faust `@timer` (short intervals) + DB-scheduled rows (business-level cron)**

```python
# Short-interval timers — Faust timer (already in codebase)
@faust_app.timer(interval=10.0, on_leader=True)  # every 10 seconds
async def retry_pending_sagas():
    ...

@faust_app.timer(interval=2.0, on_leader=True)   # every 2 seconds
async def publish_light_outbox():
    ...

# Business-level cron — DB row with next_run_at
class ScheduledJobOrm(BaseModel):
    job_name    : str
    cron_expr   : str        # "0 2 * * *"
    next_run_at : datetime
    last_run_at : datetime
    status      : str        # SCHEDULED / RUNNING / FAILED

@faust_app.timer(interval=60.0, on_leader=True)
async def job_scheduler():
    now = datetime.now(tz=timezone.utc)
    async with db.get_current_session_generator() as session:
        due_jobs = await session.scalars(
            select(ScheduledJobOrm)
            .where(ScheduledJobOrm.next_run_at <= now)
            .where(ScheduledJobOrm.status == "SCHEDULED")
            .with_for_update(skip_locked=True)
        )
        for job in due_jobs:
            job.status = "RUNNING"
            job.last_run_at = now
            job.next_run_at = compute_next_run(job.cron_expr, now)
            await session.flush()
            await run_job(job.job_name, session)
            job.status = "SCHEDULED"

# Alternative: APScheduler (if you want cron strings without writing your own)
# pip install apscheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()
scheduler.add_job(reconcile, 'cron', hour=2, timezone='UTC')
scheduler.start()
```

#### Comparison

| Dimension | Temporal Schedules | Faust timer + DB scheduler |
|-----------|-------------------|---------------------------|
| Cron expression support | Yes, built-in | Yes — `croniter` library or APScheduler |
| Timezone support | Yes | Yes — `pytz` + `datetime` |
| Missed run backfill | Yes | Yes — query `next_run_at < now - threshold` |
| Execution history | Yes — Temporal UI | Yes — `ScheduledJobOrm.last_run_at` + audit log |
| Single-worker guarantee | Yes — Temporal coordinates | Yes — `with_for_update(skip_locked=True)` |
| Infrastructure | Temporal server | PostgreSQL (already deployed) |

---

### Feature 7 — Workflow Versioning (Safe In-Flight Updates)

#### What Temporal does

`workflow.patched()` lets you safely deploy new workflow logic without breaking
workflows that are already running with the old logic. Temporal tracks which
version each running workflow was started with.

```python
# Temporal: versioning during deployment
@workflow.defn
class DepositWorkflow:
    @workflow.run
    async def run(self, payload):
        if workflow.patched("add-risk-check"):
            # New code path — only for workflows started after this deploy
            await workflow.execute_activity(risk_check, payload)
        await workflow.execute_activity(credit_balance, payload)
```

#### Pattern equivalent

**Feature flags in `saga_state.payload` + `current_step` as the version marker**

Because saga steps are stored as strings in the DB, you add new steps without
breaking in-flight sagas. In-flight sagas have a `current_step` that doesn't
match the new step — the runner treats it correctly because steps are looked up
by name, not index.

```python
# Version 1 saga steps
STEPS_V1 = {
    "PERSIST_TRANSACTION": persist_transaction,
    "CREDIT_BALANCE":      credit_balance,
    "EMIT_RISK_EVENT":     emit_risk_recalculation,
}

# Version 2 saga steps — add RISK_CHECK before CREDIT_BALANCE
# In-flight V1 sagas are at "CREDIT_BALANCE" — they skip RISK_CHECK naturally
STEPS_V2 = {
    "PERSIST_TRANSACTION": persist_transaction,
    "RISK_CHECK":          risk_check,             # ← new step
    "CREDIT_BALANCE":      credit_balance,
    "EMIT_RISK_EVENT":     emit_risk_recalculation,
}

# Feature flag controls which runner is used for NEW sagas
def make_runner():
    if settings.DEPOSIT_SAGA_V2_ENABLED:
        return SagaRunner(saga_type="deposit", steps=STEPS_V2, ...)
    return SagaRunner(saga_type="deposit", steps=STEPS_V1, ...)
```

For DB schema changes: **additive-only migrations** (new columns, never rename/drop)
ensure in-flight saga payloads remain valid across deploys.

#### Comparison

| Dimension | Temporal versioning | Feature flags + additive DB schema |
|-----------|--------------------|------------------------------------|
| In-flight safety | `workflow.patched()` gates code paths | Step names looked up by string; old step names continue working |
| New step insertion | `patched()` returns True for new flows | New step added to dict; old sagas skip it (their `current_step` is past it) |
| Schema changes | Temporal handles serialization | Additive-only DB migrations |
| Rollback | Temporal tracks version per workflow | Re-deploy V1 runner; in-flight V2 sagas complete on V2 |
| Complexity | Framework handles it | ~5 lines per version branch |

---

### Feature 8 — Visibility (Search, Filter, Inspect All Workflows)

#### What Temporal does

Temporal provides a Web UI and API to search running and historical workflows by
type, status, custom attributes, time range. You can inspect the event history,
current step, input, output, and error of any workflow.

#### Pattern equivalent

**Direct SQL on `saga_state` + distributed tracing + health check API**

```sql
-- Find all in-progress deposit sagas
SELECT saga_key, current_step, attempts, updated_at
FROM saga_state
WHERE saga_type = 'deposit'
  AND status = 'IN_PROGRESS'
ORDER BY updated_at DESC;

-- Find all sagas stuck in retry for more than 1 hour
SELECT saga_type, saga_key, current_step, attempts, last_error, retry_after
FROM saga_state
WHERE status = 'PENDING_RETRY'
  AND retry_after < now() - INTERVAL '1 hour'
ORDER BY retry_after;

-- Find all failed sagas (DLQ)
SELECT saga_type, event_id, event_type, error_message, created_at
FROM saga_failed_events
WHERE created_at > now() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Audit trail for one deposit
SELECT current_step, status, attempts, last_error, updated_at
FROM saga_state
WHERE saga_key = 'eth:mainnet:0xabc:0xaddr'
ORDER BY updated_at;
```

```python
# Health check API (FastAPI endpoint or Faust HTTP route)
@app.get("/health/sagas")
async def saga_health():
    async with db.get_current_session_generator() as session:
        counts = await session.execute(
            select(
                SagaStateOrm.status,
                func.count().label("count"),
            )
            .group_by(SagaStateOrm.status)
        )
        return {row.status: row.count for row in counts}

# Response: {"COMPLETED": 14823, "IN_PROGRESS": 3, "PENDING_RETRY": 1, "FAILED": 0}
```

```python
# Distributed tracing — each handler span links back to the source event
with ContextTracer(span_name=f"handler.{handler_name}") as ct:
    ct.set_attribute("handler.name", handler_name)
    ct.set_attribute("event.type", str(event.type))
    ct.set_attribute("saga.id", str(saga.uuid))
    ct.set_attribute("saga.step", saga.current_step)
```

#### Comparison

| Dimension | Temporal UI | SQL + Tracing |
|-----------|------------|--------------|
| Running workflows list | Yes — Web UI | `SELECT WHERE status = 'IN_PROGRESS'` |
| Historical workflows | Yes | `saga_state` retains all rows |
| Search by custom field | Yes — via search attributes | `WHERE saga_key LIKE 'eth:mainnet:%'` |
| Step-by-step event history | Full replay log | `current_step` + tracing spans |
| Error inspection | Yes — full exception visible | `saga_state.last_error` + tracing |
| Trigger retry manually | Yes — from UI | `UPDATE saga_state SET status='PENDING_RETRY'` |
| Infrastructure | Temporal server | PostgreSQL + Grafana/Kibana (already deployed) |

---

### Feature 9 — Exactly-Once Activity Execution (No Duplicate Work)

#### What Temporal does

Temporal's activity execution is idempotent by design — if an activity is
retried, the same activity `task_token` is used and the framework ensures the
result is not double-applied. Idempotency is handled by the server.

#### Pattern equivalent

**`ProcessedEventRegistry` — `ON CONFLICT DO NOTHING` on `processed_events` table**

```python
# libs/core/src/core/saga/idempotency.py
class ProcessedEventRegistry:
    @staticmethod
    async def is_processed(event_id: str, session: AsyncSession) -> bool:
        result = await session.scalar(
            select(ProcessedEventOrm).where(ProcessedEventOrm.event_id == event_id)
        )
        return result is not None

    @staticmethod
    async def mark_processed(event_id: str, event_type: str, session: AsyncSession) -> bool:
        stmt = (
            pg_insert(ProcessedEventOrm)
            .values(event_id=event_id, event_type=event_type)
            .on_conflict_do_nothing(index_elements=["event_id"])
            .returning(ProcessedEventOrm.event_id)
        )
        result = await session.execute(stmt)
        return result.first() is not None   # False = already existed → skip
```

The `ON CONFLICT DO NOTHING` + `RETURNING` is race-safe even with multiple
concurrent workers processing the same event — only one will get a row back.

#### Comparison

| Dimension | Temporal | ProcessedEventRegistry |
|-----------|---------|----------------------|
| Duplicate prevention | Server-side activity dedup | DB-side `ON CONFLICT DO NOTHING` |
| Scope | Per-workflow-execution | Per-event across all workers |
| Race safety | Temporal server serializes | PostgreSQL serializable isolation |
| Visibility | Temporal activity history | `SELECT * FROM processed_events WHERE event_id = ?` |

---

## Complete Feature Map

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  TEMPORAL FEATURE          │  PATTERN EQUIVALENT                               │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Durable Workflows         │  SagaRunner + saga_state (PostgreSQL)             │
│  (crash & resume)          │  Kafka AT_LEAST_ONCE + @idempotent                │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Activity Retry Policy     │  @retryable decorator (simple handlers)           │
│  (automatic back-off)      │  saga_state.retry_after + saga retry poller       │
│                            │  RETRY_DELAYS = [5, 30, 120, 600, 3600]           │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Activity Timeout          │  asyncio.wait_for(step(), timeout=N)              │
│                            │  CircuitBreaker (fail-fast on external APIs)      │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Non-retryable Errors      │  NonRetryableError exception class                │
│                            │  → goes directly to DLQ, no retry                 │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Durable Timers            │  DB row with next_run_at / retry_after column     │
│  (sleep days/months)       │  Faust timer polls every 10–60s                   │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Signals                   │  Kafka event → handler updates saga_state.payload │
│  (external input)          │  saga advances on next poll                        │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Queries                   │  SELECT from saga_state by saga_key               │
│  (read running state)      │  Health check API endpoint                         │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Child Workflows           │  Parent saga's final step → stage_deferred()     │
│  (composed flows)          │  Child events trigger independent child sagas     │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Schedules / Cron          │  Faust @timer (short intervals)                   │
│                            │  DB scheduled_jobs table + polling (business cron)│
│                            │  APScheduler (if cron expressions needed)         │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Workflow Versioning       │  Step names as strings (new steps skip in-flight) │
│  (safe in-flight deploy)   │  Feature flags in settings.py                     │
│                            │  Additive-only DB migrations                      │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Workflow Visibility UI    │  SQL queries on saga_state                        │
│                            │  Grafana dashboard on saga_state metrics           │
│                            │  Distributed tracing spans (ElasticAPM)           │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Exactly-Once Activity     │  ProcessedEventRegistry                           │
│  (no duplicate work)       │  ON CONFLICT DO NOTHING — race-safe               │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Compensation / Rollback   │  SagaRunner._compensate()                         │
│  (Saga pattern)            │  Registered compensation per step                 │
│                            │  FailedEventOrm on compensation failure → DLQ     │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Dead Letter Queue         │  saga_failed_events table                         │
│                            │  light_failed_events table (simple handlers)      │
│                            │  Alert: zero unresolved rows per business day     │
├────────────────────────────┼───────────────────────────────────────────────────┤
│  Parallel Activities       │  Multiple Kafka partitions + competing consumers  │
│  (fan-out)                 │  asyncio.gather() within a single saga step       │
└────────────────────────────┴───────────────────────────────────────────────────┘
```

---

## When Temporal IS Worth Adopting (For This System)

The pattern stack covers every Temporal feature. Temporal becomes worth the
operational overhead **only** if you encounter these specific needs:

| Trigger condition | Why Temporal helps here |
|-------------------|------------------------|
| Sub-second durable timer precision at high volume | Temporal's timer wheel is more efficient than DB polling at > 100k timers/sec |
| Workflow code changes while 10,000+ long-running sagas are in-flight | `workflow.patched()` is safer than string-based step versioning at that scale |
| Team is > 20 engineers all writing new flows simultaneously | Temporal SDK enforces workflow contracts better than shared saga infrastructure |
| Regulatory audit requires a tamper-proof execution history | Temporal's append-only event log is harder to accidentally corrupt than a mutable DB row |
| Visual workflow product shipped to end users | Temporal UI is faster to build on than a custom dashboard |

**None of these conditions currently apply to Floin.** The pattern stack is the
right choice for the current scale and team size.

---

## Summary

Temporal's value proposition is: *"You write plain code; we handle durability,
retries, timers, and state."*

The pattern stack's value proposition is: *"You write plain code on infrastructure
you already own; each concern is a composable, auditable, replaceable piece."*

For a financial platform at Floin's scale, the pattern stack wins because:

1. **No new operational dependency** — PostgreSQL and Kafka are already production-proven in this system
2. **DB is the source of truth** — saga state, audit logs, and locks all in PostgreSQL means one consistent view
3. **Debuggable with SQL** — any engineer can inspect, replay, or fix a stuck saga with a single SQL statement, no new SDK needed
4. **Incremental adoption** — each pattern (idempotency, outbox, saga) is deployed independently; Temporal requires full adoption
5. **Financial safety** — PostgreSQL transactions give stronger atomicity guarantees than Temporal's eventual-consistency-based history for balance-modifying operations
