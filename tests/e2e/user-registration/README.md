# Messaging Serialization — Developer Guides

> **Scope:** How events are serialized between the Python and Node services on the
> user-registration flow, and how to test all combinations.
>
> **Implemented in:** `taas-server-py/libs/foundation/src/foundation/messaging/`,
> `taas-server-js/packages/`, `floin-authorizer/packages/`

---

## The guides

| Guide | Read it when |
| --- | --- |
| [serialization.md](serialization.md) | Choosing or changing `MESSAGE_ENCODING`; understanding the wire format |
| [avro-schema-registry.md](avro-schema-registry.md) | Adding an event type, evolving a schema, or debugging Avro |
| [event-routing.md](event-routing.md) | Adding an event, or deciding which topic it belongs on |
| [troubleshooting.md](troubleshooting.md) | Something is failing — start here |
| [e2e-user-registration.md](e2e-user-registration.md) | Running the test matrix by hand |

---

## The flow in one picture

```text
POST /api/v1/auth/signup                    ews_api          (publisher)
        │
        │  writes rows to the transactional outbox (same DB txn)
        ▼
   resiliant_outbox_messages (same table / relay algorithm as taas-server-js)
        │
        │  OutboxPoller claims (SKIP LOCKED) + publishes, encoding at publish time
        ▼
   Kafka topics ── iam.user.registered ── user.directory_created
                │                       └ user.registered
                └─ iam.tenant.created ─── tenant.created
        │
        ├──────────────► ews_worker            (Python consumer)
        └──────────────► node demo consumer    (kafkajs or kafka-cp)
```

Encoding happens **at publish time**, not when the outbox row is written. The
outbox stores the event as a plain dict, so changing `MESSAGE_ENCODING` changes
how already-pending rows go out.

---

## Quick start

Four processes plus a test. Each needs its own terminal.

```bash
# 1. API (publisher)
cd taas-server-py && ./start_fastapi_ews_api.sh      # listens on :8191

# 2. Python consumer
cd taas-server-py && ./start_worker.sh

# 3. Outbox relay (publishes to Kafka)
cd taas-server-py && ./start_outbox.sh

# 4. Node consumer — pick ONE
cd taas-server-js/demos/messaging_kafka_demo && ./start-consumer.sh            # kafkajs
cd taas-server-js/demos/messaging_kafka_demo && ./start-consumer.sh kafka-cp   # confluent

# 5. Trigger the flow
cd taas-server-py/apps/ews_api/tests/performance_test/k6/test-signup-user && uv run python test_register_new_user.py
```

A healthy run produces three published events and three decoded events per
consumer.

### What "healthy" looks like

```text
# outbox
Published event user.directory_created (id=…) to iam.user.registered in 132.62ms
Published event user.registered        (id=…) to iam.user.registered in 10.64ms
Published event tenant.created         (id=…) to iam.tenant.created   in 10.46ms

# node consumer
📩 ⬅️ Decoded message: [topic=iam.user.registered, event-type=user.directory_created …]
Handling IamTenantCreatedEvent for tenant ID: 94518736      ← populated, not `undefined`
```

`tenant ID: undefined` means field loss — see
[avro-schema-registry.md](avro-schema-registry.md#2-why-one-schema-per-topic-is-wrong).

---

## Prerequisites

| Service | Where | Notes |
| --- | --- | --- |
| Kafka | `KAFKA_BOOTSTRAP_SERVERS` | SASL_SSL; needs `KAFKA_CA_DATA` for the private CA |
| Schema Registry | `KAFKA_SCHEMA_REGISTRY_URL` | Only for `schema-registry-avro`. Basic auth required |
| Postgres | `DATABASE_URL` | Outbox + app tables |
| Redis | cache config | API only |
| Keycloak | `KEYCLOAK_HOST` | Identity directory |

`SIGNUP_TEST_MODE=true` (set by `start_worker.sh`) deletes and recreates an
existing user instead of rejecting the signup, so the test is re-runnable with
the same email.

---

## Two rules that will bite you

**1. Encodings are not wire-compatible.** A message written as Avro cannot be
read as msgpack. Switching `MESSAGE_ENCODING` leaves undecodable messages on the
topic for any consumer group holding older offsets. When switching, either use
fresh topics or reset the group's offsets — see
[troubleshooting.md](troubleshooting.md#decode-fails-after-changing-message_encoding).

**2. One client library per consumer group.** `kafkajs` and
`@confluentinc/kafka-javascript` advertise different partition-assignor protocol
names, and a group whose members advertise disjoint names is rejected by the
broker. The start scripts append `-kjs` / `-cp` to the group id so the two never
collide.
