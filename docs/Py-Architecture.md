# Python Microservice Platform — Core Characteristics

> Goal: a reusable, scalable, extensible, data-serious platform with high performance, simple-but-powerful architecture, and high fault tolerance.

---

## 1. Architecture — Simple & Powerful

- **Single responsibility**: one service = one business capability (DDD bounded contexts).
- **Database per service**: no shared tables; communicate only via APIs or events.
- **Stateless services**: state lives in DB/cache/queue, never in process memory.
- **Clear contracts**: versioned schemas (OpenAPI, Protobuf/gRPC, AsyncAPI).
- **Sync + async**: direct calls (REST/gRPC) for queries; events (Kafka/NATS/RabbitMQ) for side effects.

## 2. Reusable & Extensible

- **Service chassis**: one internal library/template for config, logging, tracing, health checks, auth, DB & broker clients.
- **Hexagonal (ports & adapters)**: business logic independent of frameworks and infrastructure.
- **Event-driven extension**: add features by subscribing to events, not editing existing services.
- **Config over code**: environment-driven settings (Pydantic Settings) and feature flags.

## 3. Scalable & High Performance

- **Async I/O**: FastAPI/Litestar, asyncio, uvloop.
- **Horizontal scaling**: Kubernetes + HPA (CPU, queue lag, custom metrics).
- **Caching**: Redis for reads, idempotency keys, rate limits.
- **Fast serialization**: orjson/msgspec; Protobuf between services.
- **Pooling & batching**: asyncpg pools, batched writes and message produces.
- **Offload CPU work**: worker pools; Rust/C extensions for hot paths.

## 4. Resilient & Fault Tolerant

- **Timeouts** on every outbound call.
- **Retries** with exponential backoff + jitter (idempotent operations only).
- **Circuit breakers & bulkheads** to stop cascading failures.
- **Idempotency**: safe to repeat any request or message.
- **Graceful degradation**: fallbacks and partial responses.
- **Health checks**: liveness/readiness probes + graceful shutdown.
- **Back-pressure**: bounded queues, rate limiting at the gateway.
- **Redundancy**: multiple replicas across zones; no single point of failure.

## 5. Data Serious — Correctness First

- **Transactional outbox**: DB write and event publish never diverge.
- **Sagas**: multi-service workflows with compensating actions.
- **Event sourcing / CQRS**: where audit trails or complex reads are needed.
- **Schema evolution**: backward-compatible migrations (Alembic, schema registry).
- **Exactly-once effect**: at-least-once delivery + idempotent consumers.
- **Explicit consistency**: choose strong vs. eventual per use case, and document it.
- **Backups & PITR**: with regularly tested restores.

## 6. Observability

- **Structured logs** with correlation/trace IDs.
- **Metrics**: RED (Rate, Errors, Duration) and USE (Utilization, Saturation, Errors) via Prometheus.
- **Distributed tracing**: OpenTelemetry.
- **SLOs & alerting**: alert on user impact, not noise.

## 7. Security

- **Zero trust**: mTLS between services; OAuth2/OIDC + JWT at the edge.
- **Secrets management**: Vault / cloud KMS — never in code.
- **Least privilege**: per-service credentials.
- **Validation at every boundary**: Pydantic.

## 8. Delivery & Operations

- **Immutable containers**: one Docker image promoted across environments.
- **CI/CD**: tests, lint, type checks (mypy/pyright), security scans.
- **Safe deploys**: rolling / blue-green / canary with auto-rollback.
- **Infrastructure as Code**: Terraform, Helm.
- **Testing pyramid**: unit → contract (Pact) → integration → few end-to-end.

---

## Minimal Core Stack

| Layer | Choice |
|---|---|
| API | FastAPI + Pydantic v2 + uvicorn |
| Async messaging | Kafka (data-heavy) or NATS (simple, fast) |
| Database | PostgreSQL + asyncpg |
| Cache | Redis |
| Resilience | tenacity (retries) + circuit breaker library |
| Observability | OpenTelemetry → Prometheus / Grafana / Tempo / Loki |
| Runtime | Docker + Kubernetes |
| Edge | API gateway (Kong / Envoy / Traefik) |

---
