# libs/resiliant/src/resiliant/outbox

Generic transactional-outbox engine, bound per use case to a table at runtime — the Python twin of
`taas-server-js/packages/resiliant/src/outbox` (same tables, statuses, SQL and relay algorithm).

- `registry.py` — `OutboxDefinition(name, model, default_target)`; built-ins `messaging`, `transaction`.
- `outbox_service.py` — writers in the caller's session (`ON CONFLICT DO NOTHING` on `event_id` / `request_id`, `NOTIFY` with the notify strategy).
- `outbox_repository.py` — lock-based `claim` (`FOR UPDATE SKIP LOCKED`, ordering guard), compare-and-set `mark_published` / `mark_failed`, `requeue_dead_letters`, `purge_published`, `stats`.
- `outbox_processor.py` — one relay step in ONE transaction; `OutboxTargetCircuit` attributes failures (record vs. target down).
- `dispatchers.py` — one dispatcher per `OutboxTarget`; `OutboxDispatchRouter` picks by `record.target`.
- `outbox_poller.py` — loops the processor (drain, idle backoff, LISTEN/NOTIFY). `factory.py` — entry point (`build_outbox_pollers`).

No `processing` status. Statuses `pending` → `published` | `failed` (capped backoff) → `dead_letter`.
Settings: the JS `OUTBOX_*` names and defaults (`outbox_settings.py`). Diagram: `taas-server-py/docs/developers/resiliant-outbox.md`.
