# Avro & Schema Registry Guide

> **Scope:** How an Avro schema is chosen, registered, and evolved; and the
> guarantees that stop a field going missing in silence.
>
> **Implemented in:** `taas-server-py/libs/foundation/src/foundation/messaging/kafka/sr/`

---

## Contents

1. [The resolution model](#1-the-resolution-model)
2. [Why one schema per topic is wrong](#2-why-one-schema-per-topic-is-wrong)
3. [Registering an event type](#3-registering-an-event-type)
4. [Type mapping](#4-type-mapping)
5. [Safety guarantees](#5-safety-guarantees)
6. [Schema evolution](#6-schema-evolution)
7. [Inspecting the registry](#7-inspecting-the-registry)

---

## 1. The resolution model

Three different keys are in play. Knowing which applies where explains most
Avro behaviour.

| Layer | Keyed on | Example |
| --- | --- | --- |
| In-process lookup (encode) | `(topic, event_type)` | `('iam.user.registered', 'user.registered')` |
| Registry subject | `{topic}-{RecordName}` | `iam.user.registered-UserRegisteredEvent` |
| Decode | schema id only | `6` |

Note the encode key uses the **event_type string** while the subject uses the
**Avro record name** — two identifiers for the same event, at two layers.

### Encode: exact match, then topic fallback

```python
# schema_registry_fast.py — encode_event()
event_type = data.get('event_type') if isinstance(data, dict) else None
schema = self._get_schema(topic, event_type)      # (topic, event_type) → topic
_assert_no_field_loss(data, schema, topic=topic, event_type=event_type)
prepared = _prepare_for_avro(data, schema)
return await self._serializer.serialize(topic, prepared, schema,
                                        record_name=schema.get('name'))
```

`_get_schema` tries `_schemas_by_event[(topic, event_type)]` first and falls back
to `_avro_schemas[topic]`. The fallback is a **compatibility shim** for topics
carrying a single event type — not the intended path.

### Decode: schema id, nothing else

```python
schema_id, payload = ConfluentWireFormat.decode(data)
schema = await self.registry.get_schema_by_id(schema_id)
```

Topic and event type are irrelevant when reading. This is why:

- consumers needed no change when producers moved to per-record subjects,
- a consumer can read a topic carrying many event types with no configuration,
- a consumer in any language works as long as it can reach the registry.

---

## 2. Why one schema per topic is wrong

Topics deliberately carry many event types:

| Topic | Event types |
| --- | --- |
| `iam.auth` | 9 |
| `iam.user.registered` | 7 |
| `iam.authz` | 5 |
| `iam.tenant.created` | 4 |
| `iam.mfa` | 4 |
| `iam.sync` | 2 |

Those types are **siblings** — each a direct subclass of `BaseEvent`, not a
subclass chain — so no one schema can stand in for the rest.

Registering a single schema per topic meant every other type on that topic was
encoded with a sibling's schema. And `fastavro.schemaless_writer` **ignores dict
keys absent from the schema**, so the publish succeeded with fields missing:

```text
TenantCreatedEvent encoded with UserDirectoryCreatedEvent's schema
  → tenant_id, root_account_id silently dropped
  → consumer logs: "Handling IamTenantCreatedEvent for tenant ID: undefined"
```

The producer reported success. Nothing recorded the loss.

**The fix:** one subject per event class, following Confluent's
**TopicRecordNameStrategy**:

```text
iam.user.registered-UserDirectoryCreatedEvent
iam.user.registered-UserRegisteredEvent
iam.tenant.created-TenantCreatedEvent
```

---

## 3. Registering an event type

Registration is derived from the flow definitions — you do not call the registry
directly.

```python
# flow_registration.py
for topic, event_cls in topic_event_schema_pairs(flows, topic_for_event):
    msg_service.register_schema(topic, event_cls)
```

`topic_event_schema_pairs()` yields **one entry per event class**. Its
predecessor `topic_to_schema_event()` collapsed to one per topic and is kept only
for callers needing a representative class — never use it for registration.

### Adding an event

1. Define the class in `auth_events.py` (or your domain equivalent):

   ```python
   class UserEmailVerifiedEvent(BaseEvent, kw_only=True):
       event_type: str = field(default=IamEvents.USER_EMAIL_VERIFIED)
       email: str = ''
       verified_at: str | None = None
   ```

2. Map it to a topic in `EVENT_TOPIC_MAPPING` (`iam_constants.py`).

3. Reference it from a flow in `IAM_ALL_FLOWS` — as a `step.event` or in
   `step.emits`. **If it is not in a flow, no schema is registered for it**, and
   publishing it raises rather than corrupting.

4. Publish it via the resolver, never a hard-coded topic:

   ```python
   await self.message_routing_service.publish_event(
       event,
       channel=get_iam_topic_for_event(IamEvents.USER_EMAIL_VERIFIED),
       session=session,
   )
   ```

   See [event-routing.md](event-routing.md) for why.

The subject is created in the registry on first publish, not at registration.
A topic nothing has published to has no subject yet.

---

## 4. Type mapping

`serializer.py` maps `msgspec.Struct` annotations to Avro.

| Python | Avro | Why |
| --- | --- | --- |
| `str` | `string` | |
| `int` | `long` | Python ints are unbounded; `int` would truncate |
| `float` | `double` | Python floats are C doubles; `float` loses precision |
| `bool` | `boolean` | Checked before `int` — `bool` subclasses `int` |
| `bytes` | `bytes` | |
| `Decimal` | `string` | **Exact.** Avro's decimal logical type needs a fixed precision/scale that a bare annotation lacks; `double` would round money |
| `UUID` | `string` | |
| `datetime` | `long` / `timestamp-micros` | Logical type activates the ISO-string coercion in `_prepare_for_avro` |
| `date` | `int` / `date` | |
| `X \| None` | `["null", X]`, `default: null` | `null` leads so the default is legal |
| `list[X]` | `array` of X | |
| `dict[str, X]` | `map` of X | Avro map keys are always strings |
| nested `Struct` | `record` | Repeat references emit the bare name — Avro rejects redefinition |
| `Enum` | `enum` of member names | |
| anything else | `string` **+ WARNING** | Silent coercion is how a value-bearing field becomes unreadable |

Only statically-known defaults are emitted. A `default_factory` (`event_id`,
`timestamp`) cannot be expressed in a schema and is omitted.

### Nullability

`Optional[str]` must become `["null", "string"]`, not `"string"`. A required
`string` holding `None` fails with:

```text
TypeError: must be string on field source
```

Both spellings work — `Optional[str]` and `str | None`.

---

## 5. Safety guarantees

### `AvroFieldLossError` — no silent field loss

Before encoding, every data field is checked against the schema:

```python
dropped = sorted(set(data) - schema_fields)
if dropped:
    raise AvroFieldLossError(...)   # names the fields, topic, and schema
```

Only **extra** data fields are an error. Fields in the schema but absent from the
data are fine — Avro fills them from their default, which is normal
forward-compatible reading.

This converts a whole class of bug from *silent corruption* into a *loud failure
at publish*. For value-bearing events that trade is always worth making.

Practical consequence: an event whose type has no registered schema now **fails
to publish** rather than being encoded with a sibling's schema. If you see it,
the event is missing from its flow (step 3 above).

### Loud fallback

Any annotation the mapper cannot handle logs a WARNING naming the type. It still
falls back to `string` so one odd field cannot block a whole topic, but the
coercion is on the record.

---

## 6. Schema evolution

Evolution is **per subject**, so per `(topic, record)`. `UserRegisteredEvent` can
change without touching `UserDirectoryCreatedEvent`, even sharing a topic.

Safe changes (backward compatible — old readers still work):

- add a field **with a default**
- widen `int` → `long`, `float` → `double`
- add a branch to a union

Unsafe:

- add a field **without** a default
- remove or rename a field (rename = remove + add)
- narrow a type
- change a field's type incompatibly

`register_schema` returns the existing id for a byte-identical schema, so
restarts do not create versions. A *changed* schema creates a new version and is
checked against the subject's compatibility rule — a `409` on publish means the
change was rejected. Fix the schema; do not delete the subject in any environment
whose messages still matter, since existing messages reference the old id.

---

## 7. Inspecting the registry

```bash
SR=$KAFKA_SCHEMA_REGISTRY_URL
AUTH="$KAFKA_SCHEMA_REGISTRY_USERNAME:$KAFKA_SCHEMA_REGISTRY_PASSWORD"

curl -s -u "$AUTH" "$SR/subjects" | jq                                  # all subjects
curl -s -u "$AUTH" "$SR/subjects/iam.user.registered-UserRegisteredEvent/versions" | jq
curl -s -u "$AUTH" "$SR/subjects/<subject>/versions/latest" | jq -r .schema | jq
curl -s -u "$AUTH" "$SR/schemas/ids/6" | jq -r .schema | jq             # by embedded id
```

A `-value` subject (e.g. `iam.user.registered-value`) is a leftover from the old
one-schema-per-topic strategy. Harmless, but nothing writes it any more.

### Checking a schema without a broker

```python
from foundation.messaging.kafka.sr.serializer import schema_cls_to_avro_schema
from iam.auth.auth_events import UserRegisteredEvent
import json

print(json.dumps(schema_cls_to_avro_schema(UserRegisteredEvent), indent=2))
```

Cheaper than a round trip, and the fastest way to confirm a new field mapped the
way you expected.
