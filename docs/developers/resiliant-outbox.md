# Resiliant outbox — components and communication

How the transactional outbox works: one generic engine, one table per use case — the
Python twin of `@taas/resiliant` (taas-server-js): same tables in the shared database,
same SQL and relay algorithm, so either relay can serve the same rows. Code: `libs/resiliant/src/resiliant/outbox`, models:
`libs/resiliant/src/resiliant/models/outbox.py`, contracts:
`libs/foundation/src/foundation/resiliant/outbox.py`.

## Layers

| Layer | Package | Holds |
| --- | --- | --- |
| Contracts | `foundation.resiliant.outbox` | `IOutboxService` (messaging), `ITransactionOutboxService`, `IOutboxRecord`, `IOutboxDispatcher`, `OutboxTarget`, `OutboxName`, `OutboxStatus`, `OutboxConfig` |
| Factory contract | `foundation.resiliant.types` | `ResiliantServiceFactoryT.get_messaging_outbox_service()`, `.get_transaction_outbox_service(target)` (`get_outbox_service()` = messaging alias) |
| Implementation + models | `resiliant` | registry, services, repository, processor, dispatchers, poller, factory, SQLAlchemy tables |
| Migrations | `resiliant.migrations` | the drizzle DDL of `@taas/resiliant` (vendored), run first by `python -m db.migrations upgrade`; Alembic ignores `resiliant_*` |

Dependency direction: `foundation` ← `resiliant` ← `db` (migration runner only) and the apps.
`foundation` never imports `resiliant`; it resolves implementations from the service
registry (`IOutboxService`, `ITransactionOutboxService`, `IDLQService`, `IIdempotencyService`,
`IRetryPolicyFactory`, …) filled by `FoundationFactory.use_resiliant(ResiliantServiceFactory())`.

## Use cases (one table each)

| Outbox (`OutboxName`) | Table | Extra columns | Service |
| --- | --- | --- | --- |
| `messaging` | `resiliant_outbox_messages` | `event_id`, `source_service`, `user_id` | `MessagingOutboxService` (`save_event`, `save_raw_message`) |
| `transaction` | `resiliant_outbox_transactions` | `request_id` (unique), `account_ref`, `source_system`; `transaction_type` = `event_type` | `TransactionOutboxService` (`save_transaction`, idempotent on `request_id`) |

Shared columns (`OutboxRecordMixin`): `id` (bigint identity = claim order), `event_type`, `target`,
`channel`, `ordering_key`, `payload` (jsonb object), `headers`, `status` (`pending` · `published` ·
`failed` · `dead_letter`), `retry_count`, `max_retries`, `last_error`, `next_attempt_at`,
`processed_at`, `correlation_id`, `created_at`, `updated_at`.

## Write path (inside the business transaction)

```text
API / domain service
  └─ ResiliantServiceFactory().get_transaction_outbox_service(target=OutboxTarget.MESSAGING)
       └─ TransactionOutboxService.save_transaction(session, request_id=…, …)
            ├─ INSERT … ON CONFLICT DO NOTHING RETURNING   (status=pending, target=messaging)
            └─ conflict → the stored record (same request_id)   [+ pg_notify with the notify strategy]
  └─ session.commit()   ← domain rows + outbox record commit atomically
```

Domain events take the same path through `MessageRoutingService` (foundation) →
`IOutboxService.save_event` → `resiliant_outbox_messages` (routing strategy `outbox`;
`direct` channels skip the outbox and publish immediately).

## Relay path (`apps/outbox_worker`, `./start_outbox.sh`)

```text
OutboxWorker
  └─ build_outbox_pollers(session_factory, publisher=messaging_service, outboxes=OUTBOX_POLL_OUTBOXES)
       └─ one OutboxPoller per outbox table (+ SchedulerPoller)
            loop: OutboxProcessor.process_batch()                 ── ONE transaction ──
              repository.claim()        SELECT … WHERE status in ('pending','failed') AND due
                                        [ordering guard] ORDER BY id FOR UPDATE SKIP LOCKED
              for record: dispatch with OUTBOX_DISPATCH_TIMEOUT_MS
                             └─ dispatcher[record.target] (messaging → MessagingServiceT.publish → Kafka)
              mark_published(ids) / mark_failed(record)      CAS on the claimable statuses
                 failure while the circuit is closed → retry_count+1, backoff min(mult**n s, max)
                 … at max_retries → dead_letter;  N distinct failures → circuit open (not counted)
            commit (a crash rolls back: the rows are claimable again)
            drain when the batch was full, else idle sleep (fixed | adaptive | notify + LISTEN)
```

No `processing` status and no stale-reset job: locks vanish with the transaction. Retention and
the other housekeeping run in the `resiliant:maintenance` cron job.

## Extending

- **New use case**: a drizzle migration in taas-server-js (`createOutboxTable`) synced here, a
  model `class XOutboxTable(OutboxRecordMixin, ResiliantBase)`,
  `register_outbox(OutboxDefinition(name='x', model=XOutboxTable))`. Use
  `factory.build_outbox_service('x').enqueue(session, event_type=…, payload=…, **columns)`;
  the worker polls it automatically.
- **New target** (e.g. HTTP webhook): add the value to `OutboxTarget`, implement
  `IOutboxDispatcher` (`target` + `async dispatch(record)`), pass it to the pollers
  (`build_outbox_pollers(dispatchers=[…])`). Services accept `target=` per record.
