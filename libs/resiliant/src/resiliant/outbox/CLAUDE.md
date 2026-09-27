# libs/resiliant/src/resiliant/outbox

Generic transactional-outbox engine, bound per use case to a table at runtime.

- `registry.py` — `OutboxDefinition(name, model, default_target)`; built-ins `messaging`, `transaction`.
- `outbox_service.py` — `OutboxService.enqueue` (any outbox), `MessagingOutboxService`, `TransactionOutboxService`.
- `outbox_repository.py` — claim (`FOR UPDATE SKIP LOCKED`), publish/fail (backoff → `DEAD_LETTER`), stats; works on any `OutboxRecordMixin` model.
- `dispatchers.py` — one dispatcher per `OutboxTarget`; `OutboxDispatchRouter` picks by `record.target`.
- `outbox_poller.py` — relay loop for ONE table. `factory.py` — entry point (`build_outbox_pollers` for the worker).

Only touch the mixin columns in generic code; use-case columns belong to the specific service.
Diagram and extension steps: `taas-server-py/docs/developers/resiliant-outbox.md`.
