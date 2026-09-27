"""
Definitions (types, configs, enums, errors, protocols) of the resilience patterns:
circuit breaker, bulkhead, timeout, fallback, retry, outbox, saga, idempotency,
dead-letter queue and schedules.

Only definitions live here; every implementation (services, repositories, settings
loaders) is in the ``resiliant`` library, wired via ``FoundationFactory.use_resiliant``.
"""
