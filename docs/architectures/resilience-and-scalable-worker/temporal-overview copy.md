# Temporal — Overview

> **Temporal** ([github.com/temporalio/temporal](https://github.com/temporalio/temporal)) is a **durable execution platform** — it runs code that must reliably complete even across failures, crashes, restarts, or long waits.

---

## Core Functionalities

- **Durable Workflows**: Functions that survive process crashes and resume from exactly where they left off (state is persisted automatically)
- **Activities**: Individual units of work (API calls, DB writes, etc.) with automatic retry policies and timeouts
- **Timers**: Sleep for seconds or *years* reliably — `workflow.sleep(30 days)` just works
- **Signals & Queries**: Send data into a running workflow or query its current state from outside
- **Child Workflows**: Compose complex workflows from smaller sub-workflows
- **Schedules / Cron**: Run workflows on a recurring schedule
- **Versioning**: Safely deploy updated workflow logic without breaking in-flight executions
- **Visibility**: Search, filter, and inspect all running/historical workflows via UI or API

---

## Real-World Use Cases

| Use Case | Description |
|---|---|
| **Payment processing** | Multi-step checkout: charge card → reserve inventory → send confirmation. Retry failed steps, never double-charge |
| **User onboarding** | KYC verification flow that waits days/weeks for document approval before progressing |
| **Order fulfillment** | Coordinate warehouse pick → ship → track → deliver, handling failures at each step |
| **Data pipelines** | ETL jobs that process millions of records, resuming from the last checkpoint on failure |
| **Subscription billing** | Sleep until next billing date, charge, handle failures, retry — all in a single workflow function |
| **Crypto/blockchain indexing** | Process transactions, handle RPC failures with retries, coordinate across multiple chains |
| **Saga pattern** | Distributed transactions with compensating rollbacks (e.g., hotel + flight booking) |
| **AI agent orchestration** | Long-running LLM pipelines that call external tools, wait for human approval, or retry on rate limits |

---

## The Key Insight

Without Temporal, you'd need **message queues + databases + cron jobs + retry logic + state machines** all stitched together.

Temporal replaces all of that — you write **plain code** and it handles durability, retries, timeouts, and state automatically.
