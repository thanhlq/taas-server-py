# Event Routing Guide

> **Scope:** How an event reaches a topic, and why the topic must never be
> hard-coded at the publish site.
>
> **Implemented in:** `taas-server-py/libs/iam/src/iam/iam_constants.py`,
> `libs/foundation/src/foundation/messaging/events/flow_registration.py`

---

## One resolver, two consumers of it

`EVENT_TOPIC_MAPPING` in `iam_constants.py` is the single source of truth for
"which topic does this event belong on". Two independent things read it:

```text
                    EVENT_TOPIC_MAPPING
                   (event_type → topic)
                            │
        ┌───────────────────┴───────────────────┐
        ▼                                       ▼
  get_iam_topic_for_event()            topic_event_schema_pairs()
  → the channel you publish to         → the Avro schema registered
```

Both must agree. If a publish site hard-codes a topic, the event is encoded with
whatever schema *that* topic holds — which belongs to a different event type.

Always route through the resolver:

```python
from iam.iam_constants import IamEvents, get_iam_topic_for_event

await self.message_routing_service.publish_event(
    event,
    channel=get_iam_topic_for_event(IamEvents.TENANT_CREATED),
    session=session,
)
```

Never:

```python
# ✗ diverges from schema registration the moment the mapping changes
await self.message_routing_service.publish_event(
    event, channel=IamTopics.IAM_USER_REGISTER, session=session
)
```

---

## What divergence actually did

Three publish sites had hard-coded channels that disagreed with the mapping:

| Site | Published to | Mapping says | Result |
| --- | --- | --- | --- |
| `_admin.py` — `TenantCreatedEvent` | `iam.user.registered` | `iam.tenant.created` | Encoded with `UserDirectoryCreatedEvent`'s schema; `tenant_id` and `root_account_id` silently dropped → consumer saw `tenant ID: undefined` |
| `_users.py` — `UserRegisteredEvent` | `iam.auth` | `iam.user.registered` | `iam.auth` has no schema for it → publish failed under Avro |
| `_users.py` — `TenantCreatedEvent` | `iam.auth` | `iam.tenant.created` | Same |

Note the two failure modes. The `iam.auth` cases failed loudly, so they would
have been found. The `_admin.py` case *succeeded* and lost data — the dangerous
one, and the reason `AvroFieldLossError` now exists.

---

## The topic map

```python
# iam_constants.py
EVENT_TOPIC_MAPPING = {
    IamEvents.USER_DIRECTORY_CREATED: IamTopics.IAM_USER_REGISTER,   # iam.user.registered
    IamEvents.USER_REGISTERED:        IamTopics.IAM_USER_REGISTER,
    IamEvents.TENANT_CREATED:         IamTopics.IAM_TENANT_CREATED,  # iam.tenant.created
    ...
}
```

Current grouping — several event types per topic is intentional:

| Topic | Types | Examples |
| --- | --- | --- |
| `iam.auth` | 9 | `user.authenticated`, `session.created`, `user.password_changed` |
| `iam.user.registered` | 7 | `user.directory_created`, `user.registered`, `user.email_verified` |
| `iam.authz` | 5 | `user.role_assigned`, `user.permissions_changed` |
| `iam.tenant.created` | 4 | `tenant.created`, `tenant.updated`, `tenant.suspended` |
| `iam.mfa` | 4 | `mfa.enabled`, `mfa.verification_failed` |
| `iam.sync` | 2 | `user.synced_to_provider` |

Grouping by aggregate keeps ordering guarantees where they matter — everything
about one user's registration lands on one topic, so one partition, so in order.

Under Avro this is safe **only** because each type has its own subject. See
[avro-schema-registry.md](avro-schema-registry.md#2-why-one-schema-per-topic-is-wrong).

---

## Adding an event: the checklist

1. **Define** the event class, subclassing `BaseEvent`. Use `msgspec.field` for
   defaults — `dataclasses.field` would store the `Field` object verbatim and
   break serialization.

2. **Add** it to `IamEvents` and to `EVENT_TOPIC_MAPPING`.

3. **Reference** it in a flow (`IAM_ALL_FLOWS`), as a `step.event` or in
   `step.emits`. This is what registers its schema. Skipping it means Avro
   publishes of that event raise.

4. **Publish** through `get_iam_topic_for_event(...)`.

5. **Subscribe** — add the topic to `CONSUMER_CHANNELS` (Python) and `TOPICS`
   (Node) if it is a new topic.

6. **Verify** the generated schema before running anything:

   ```python
   from foundation.messaging.kafka.sr.serializer import schema_cls_to_avro_schema
   import json
   print(json.dumps(schema_cls_to_avro_schema(MyNewEvent), indent=2))
   ```

### `EVENT_TOPIC_MAPPING.get(event_type, IamTopics.IAM)` — the default

An unmapped event falls back to the `iam` topic rather than raising. That topic
has no registered schema, so under Avro the publish fails with "No Avro schema
registered for topic 'iam'". If you see that, step 2 was missed.

---

## Consumers, handlers, and the outbox

Two registrations happen from the same flow definitions:

```python
register_handlers_from_flows(...)      # event_type → handler
register_schema_registry_schemas(...)  # (topic, event_type) → Avro schema
```

Handler registration **returns early when the consumer is disabled**
(`CONSUMER_ENABLED=false`), but schema registration does not — a publisher-only
service still needs schemas. That asymmetry is deliberate.

A consumer receiving an event with no registered handler logs
`No handler found for event type: …` and moves on. Not an error — just an event
nobody is listening for yet.

Publishing goes through the **transactional outbox**: `publish_event` writes a
row in the caller's DB transaction, and `OutboxPoller` relays it. So a publish
is only as durable as the transaction that wrote it, and the topic is fixed at
*write* time while the encoding is applied at *publish* time.
