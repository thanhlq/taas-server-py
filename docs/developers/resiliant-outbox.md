# Resiliant outbox — components and communication

How the transactional outbox works after the 2026-09 refactor: one generic engine,
one table per use case. Code: `libs/resiliant/src/resiliant/outbox`, models:
`libs/resiliant/src/resiliant/models/outbox.py`, contracts:
`libs/foundation/src/foundation/resiliant/outbox.py`.

## Layers

| Layer | Package | Holds |
| --- | --- | --- |
| Contracts | `foundation.resiliant.outbox` | `IOutboxService` (messaging), `ITransactionOutboxService`, `IOutboxRecord`, `IOutboxDispatcher`, `OutboxTarget`, `OutboxName`, `OutboxStatus`, `OutboxConfig` |
| Factory contract | `foundation.resiliant.types` | `ResiliantServiceFactoryT.get_messaging_outbox_service()`, `.get_transaction_outbox_service(target)` (`get_outbox_service()` = messaging alias) |
| Implementation + models | `resiliant` | registry, services, repository, dispatchers, poller, factory, SQLAlchemy tables |
| Migrations | `db` | single Alembic tree; `db/migrations/env.py` imports `resiliant.models` |

Dependency direction: `foundation` ← `resiliant` ← `db` (migrations only) and the apps.
`foundation` never imports `resiliant`; it resolves implementations from the service
registry (`IOutboxService`, `ITransactionOutboxService`, `IDLQService`, `IIdempotencyService`,
`IRetryPolicyFactory`, …) filled by `FoundationFactory.use_resiliant(ResiliantServiceFactory())`.

## Use cases (one table each)

| Outbox (`OutboxName`) | Table | Extra columns | Service |
| --- | --- | --- | --- |
| `messaging` | `resiliant_outbox_messages` | `event_id`, `source_service`, `user_id` | `MessagingOutboxService` (`save_event`, `save_raw_message`) |
| `transaction` | `resiliant_outbox_transactions` | `request_id` (unique), `account_ref`, `source_system`; `transaction_type` = `event_type` | `TransactionOutboxService` (`save_transaction`, idempotent on `request_id`) |

Shared columns (`OutboxRecordMixin`): `event_type`, `target`, `channel`, `ordering_key`,
`payload`, `headers`, `status`, `retry_count`, `max_retries`, `last_error`,
`next_attempt_at`, `processed_at`, `correlation_id`, `created_at`, `updated_at`.

## Write path (inside the business transaction)

```text
API / domain service
  └─ ResiliantServiceFactory().get_transaction_outbox_service(target=OutboxTarget.MESSAGING)
       └─ TransactionOutboxService.save_transaction(session, request_id=…, …)
            ├─ repository.find_one(request_id)            → existing record? return it
            └─ SAVEPOINT: INSERT resiliant_outbox_transactions (status=PENDING, target=MESSAGING)
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
            loop:
              repository.fetch_pending_batch()   SELECT … FOR UPDATE SKIP LOCKED → PROCESSING
              for record: OutboxDispatchRouter.dispatch(record)
                             └─ dispatcher[record.target]   (MESSAGING → MessagingOutboxDispatcher
                                                              → MessagingServiceT.publish(channel, payload,
                                                                headers, ordering_key) → Kafka)
                ok   → repository.mark_published()          PUBLISHED
                error→ repository.mark_failed()             FAILED, next_attempt_at = now + multiplier**attempt s
                                                            … at max_retries → DEAD_LETTER (terminal)
            maintenance: reset_stale_processing() (crashed pollers), stats log
```

Claimable = `PENDING`, or `FAILED` whose `next_attempt_at` has passed, under the retry
cap and younger than 7 days.

## Extending

- **New use case**: a table `class XOutboxTable(OutboxRecordMixin, UUIDv7AuditBase)`,
  `register_outbox(OutboxDefinition(name='x', model=XOutboxTable))`, a migration. Use
  `factory.build_outbox_service('x').enqueue(session, event_type=…, payload=…, **columns)`;
  the worker polls it automatically.
- **New target** (e.g. HTTP webhook): add the value to `OutboxTarget`, implement
  `IOutboxDispatcher` (`target` + `async dispatch(record)`), pass it to the pollers
  (`build_outbox_pollers(dispatchers=[…])`). Services accept `target=` per record.
