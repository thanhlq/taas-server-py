# foundation.resiliant — definitions only

Types, configs, enums, errors and protocols of the resilience patterns. **No
implementations or settings loaders here** — they live in `libs/resiliant`, and are
exposed to foundation code through the service registry
(`FoundationFactory.use_resiliant(ResiliantServiceFactory())`).

| Module | Definitions | Implementation (`libs/resiliant`) |
| --- | --- | --- |
| `bulkhead` | `BulkheadConfig`, errors, `IBulkheadRepository` | `resiliant.bulkhead` |
| `circuit_breaker` | `CircuitBreakerConfig`, `CircuitState`, errors, `ICircuitBreakerRepository` | `resiliant.circuit_breaker` |
| `timeout` / `fallback` | configs, errors | `resiliant.timeout` / `resiliant.fallback` |
| `retry` | `IRetryPolicy`, `IRetryPolicyFactory` | `resiliant.retry` (`TenacityRetry`, `retry`) |
| `dlq` | `DeadLetterConfig`, `DLQStatus`, `IDLQService`, … | `resiliant.dlq` |
| `idempotency` | `IdempotencyConfig`, `IdempotencyBackend`, `IIdempotencyStore`, `IIdempotencyService` | `resiliant.idempotency` |
| `outbox` | `OutboxConfig`, `OutboxTarget`, `IOutboxService`, `ITransactionOutboxService`, … | `resiliant.outbox` |
| `saga` / `schedule` | configs, records, `ISagaService`, `IScheduleService`, … | `resiliant.saga` / `resiliant.schedule` |
| `types` | `ResiliantServiceFactoryT` (the factory contract) | `resiliant.ResiliantServiceFactory` |

Composite executor (`ResilientExecutor`): `resiliant.resilient_call`.
