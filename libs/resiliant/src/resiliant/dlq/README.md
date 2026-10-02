# dlq (dead-letter queue)

Twin of `@taas/resiliant/dlq` (taas-server-js) on the same `resiliant_dlq_events` tables:

- contracts (statuses, `DLQ_TRANSITIONS`, `DeadLetterConfig`): `libs/foundation/src/foundation/resiliant/dlq.py`
- models: `libs/resiliant/src/resiliant/models/dlq.py`
- `dlq_repository.py` (compare-and-set transitions, lease claim, archive), `dlq_service.py`
  (`DLQService`, `DLQHandlerRegistry`, `DLQRetryProcessor`), `dlq_settings.py` (`DLQ_*`)

Rules: `libs/resiliant/CLAUDE.md` (DLQ section).
