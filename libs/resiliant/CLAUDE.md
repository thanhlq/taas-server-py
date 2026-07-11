# Resiliant

Implementations for service resilience in microservices

Containing patterns as outbox, bulkheads, retries, Circuit Breakers,...

## Key points

- These service interfaces are defined in platform_cores.reslient
- The database models are defined in libs/db/src/db/models/resiliant
- This package is normally implementation all interfaces defined in libs/foundation/src/foundation/resiliant
  - Espcially repositories
