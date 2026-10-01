# Troubleshooting

> **Scope:** Failures actually hit on this flow, with the cause and the fix.
> Every entry here is a real diagnosis, not a hypothetical.

---

## Symptom index

| Symptom | Jump to |
| --- | --- |
| `must be string on field <name>` | [1](#1-typeerror-must-be-string-on-field-source) |
| `No Avro schema registered for topic '…'` | [2](#2-no-avro-schema-registered-for-topic) |
| `Refusing to encode … would be silently dropped` | [3](#3-avrofieldlosserror) |
| `Schema registry is not enabled (current end=msgpack)` | [4](#4-schema-registry-is-not-enabled-on-msgpack--json) |
| `Failed to decode Avro data: fetch failed` | [5](#5-fetch-failed-when-decoding) |
| Consumer logs `tenant ID: undefined` | [6](#6-a-field-arrives-as-undefined) |
| `Broker: Inconsistent group protocol` | [7](#7-inconsistent-group-protocol) |
| Thousands of `Unable connect to node` lines | [8](#8-aiokafka-error-flood-on-broker-restart) |
| Decode fails after changing `MESSAGE_ENCODING` | [9](#decode-fails-after-changing-message_encoding) |
| Consumer starts but receives nothing | [10](#10-consumer-receives-nothing) |

---

## 1. `TypeError: must be string on field source`

```text
File "fastavro/_write.pyx", line 130, in fastavro._write.write_utf8
AttributeError: 'NoneType' object has no attribute 'encode'
TypeError: must be string on field source
```

**Cause.** The field is `Optional[str]` in Python but the Avro schema declares a
required `"string"`. The value is `None`, which a non-nullable string cannot
hold. Historically the type mapper looked up `field.type` in a dict keyed by bare
types; `str | None` is not such a key, so it fell through to the `'string'`
default.

**Fix.** Nullable fields must map to `["null", "string"]` with `default: null`.
Confirm what was generated:

```python
from foundation.messaging.kafka.sr.serializer import schema_cls_to_avro_schema
s = schema_cls_to_avro_schema(MyEvent)
print(next(f for f in s['fields'] if f['name'] == 'source'))
# {'name': 'source', 'type': ['null', 'string'], 'default': None}
```

**Note the field named in the error is just the first one hit.** Avro writes
fields in schema order, so a `datetime` mapped to `"string"` fails on `timestamp`
before ever reaching `source`.

---

## 2. `No Avro schema registered for topic '…'`

**Cause A — the process never registered any schemas.** Registration happens via
`IamFactory.initialize_iam()` → `register_event_handlers_for_app_module()`. A
worker that skips it has an empty schema map. This is what broke `outbox_worker`:
it initialised messaging but never IAM.

Check quickly:

```python
svc = get_service(MessagingServiceT)
print(sorted(svc.schema_registry_encoder.avro_schemas.keys()))   # [] means nothing registered
```

**Cause B — the event is not in a flow.** Schemas are derived from
`IAM_ALL_FLOWS`. An event absent from every flow gets no schema.

**Cause C — publishing to the wrong topic.** The mapped topic has a schema; the
hard-coded one does not. See [event-routing.md](event-routing.md).

---

## 3. `AvroFieldLossError`

```text
Refusing to encode tenant.created for topic 'iam.user.registered' with schema
'UserDirectoryCreatedEvent': field(s) ['root_account_id', 'tenant_id'] are not
in the schema and would be silently dropped.
```

**This is the guard working.** Before it existed, this exact situation published
successfully with those fields missing.

**Cause.** The schema resolved for `(topic, event_type)` belongs to a different
event type — either the event is publishing to a topic that isn't its mapped one,
or its own type was never registered so the topic-level fallback picked a
sibling's schema.

**Fix.** Either publish via `get_iam_topic_for_event(...)`, or add the event to a
flow so it gets its own schema. Do not "fix" this by widening a schema to cover
both events.

---

## 4. `Schema registry is not enabled` on msgpack / json

```text
RuntimeError: Schema registry is not enabled (current end=msgpack).
Set MESSAGE_ENCODING=schema-registry-avro in your environment to enable it.
```

**Cause.** `schema_registry_encoder` raises unless Avro is configured, and it was
being passed eagerly:

```python
# ✗ Python evaluates arguments before the call — raises even though unused
sr_encoder=self.schema_registry_encoder
```

**Fix.** Use the non-raising accessor for pass-through positions:

```python
sr_encoder=self.schema_registry_encoder_or_none
```

Keep the strict property for callers that genuinely require Avro. A regression
test asserts no pass-through site uses the eager form.

---

## 5. `fetch failed` when decoding

```text
MsgDecoderError: Failed to decode Avro data: fetch failed
```

**`fetch failed` is Node's undici wrapper — the real reason is on `error.cause`.**
The decode path unwraps it now:

```text
fetch failed <- caused by AggregateError (code=ECONNREFUSED):
  [connect ECONNREFUSED ::1:8081; connect ECONNREFUSED 127.0.0.1:8081]
```

**Common causes:**

| Cause chain shows | Meaning |
| --- | --- |
| `ECONNREFUSED …:8081` | `KAFKA_SCHEMA_REGISTRY_URL` unset → defaulted to `http://localhost:8081` |
| TLS / cert error | `https://` against a plain-HTTP listener, or a private CA Node does not trust |
| `Schema Registry error 401` | Missing `KAFKA_SCHEMA_REGISTRY_USERNAME` / `PASSWORD` |
| `Schema Registry error 404` | The message references a schema id that no longer exists |

**Verify config and reachability:**

```bash
curl -s -u "$KAFKA_SCHEMA_REGISTRY_USERNAME:$KAFKA_SCHEMA_REGISTRY_PASSWORD" \
  "$KAFKA_SCHEMA_REGISTRY_URL/subjects" | jq
```

Check the scheme. A TLS handshake failing at the record layer while plain HTTP
returns `200` means the listener is HTTP-only — use `http://`.

---

## 6. A field arrives as `undefined`

```text
Handling IamTenantCreatedEvent for tenant ID: undefined
```

**Cause.** The event was encoded with a schema that lacks that field, and
`fastavro.schemaless_writer` drops unknown dict keys without complaint.

**This can no longer happen silently** — it now raises `AvroFieldLossError`
(entry 3). If you see `undefined` on an old message, the message itself is
already missing the field; re-publishing is the only fix.

Confirm which fields the registered schema actually carries:

```bash
curl -s -u "$AUTH" "$SR/subjects/<topic>-<RecordName>/versions/latest" \
  | jq -r .schema | jq '[.fields[].name]'
```

---

## 7. `Inconsistent group protocol`

```text
KafkaJSProtocolError: Broker: Inconsistent group protocol
```

**Cause.** Members of one consumer group advertise disjoint partition-assignor
protocol names. The broker intersects those lists and finds nothing shared:

| Client | Advertises |
| --- | --- |
| `kafkajs` | `RoundRobinAssigner` |
| `@confluentinc/kafka-javascript` | `roundrobin` |

Semantically both are round-robin; the *names* differ, and names are what the
broker compares.

**Fix.** One client library per group. The start scripts append `-kjs` / `-cp` to
the group id. If you hit it anyway, a stale member is still in the group — stop
it and wait out `sessionTimeout` (30s), then check:

```bash
kafka-consumer-groups.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVERS" \
  --command-config client.properties --describe --group <group>
```

Do not `--delete` the group; that discards committed offsets.

**Do not try to make them share a group.** You would need a custom kafkajs
assigner named `roundrobin` *and* librdkafka's exact assignment algorithm —
disagree on any edge case and you get overlapping or orphaned partitions.

---

## 8. aiokafka error flood on broker restart

```text
ERROR | aiokafka | Unable connect to node with id 1: [Errno 61] Connect call failed
ERROR | aiokafka | Unable to update metadata from [1]
… thousands of identical lines
```

**Cause.** aiokafka logs one ERROR per retry attempt, and its default
`retry_backoff_ms` is `100` — roughly 74 lines/second while a broker is down.

**Fixed by two things:**

- `KAFKA_RETRY_BACKOFF_MS=1000` (was aiokafka's 100) — cuts the churn at source.
- A throttling filter that collapses repeats into a periodic summary:

```text
ERROR | aiokafka | Unable connect to node with id 1: … [+238 identical suppressed in the last 60s]
```

Measured over a 20s outage: 1,475 records → 27.

Tunables: `KAFKA_LOG_THROTTLE_ENABLED`, `KAFKA_LOG_THROTTLE_BURST`,
`KAFKA_LOG_THROTTLE_INTERVAL_S`.

---

## 9. Decode fails after changing `MESSAGE_ENCODING`

**Cause.** Encodings are not wire-compatible. Messages already on the topic were
written with the old codec; a consumer group holding older offsets replays them
through the new one.

This is **not** a bug in the new encoding. Distinguishing feature: the failures
are on *old* offsets, while newly published messages decode fine.

**Fix — pick one:**

- Use a fresh consumer group with `KAFKA_AUTO_OFFSET_RESET=latest` so only new
  messages are read (this is what the test harness does).
- Reset the existing group's offsets to the end.
- Use different topics per encoding.

For a real deployment, treat an encoding change as a migration: new topics, or a
coordinated stop → offset reset → start.

---

## 10. Consumer receives nothing

Consumer starts, no decode errors, zero messages.

**Check in this order:**

1. **Did it actually start?** A `ConfigError` during construction leaves the
   process up but not consuming:

   ```text
   ❌ consumer demo failed to start: ConfigError: MESSAGE_ENCODING=schema-registry-avro
      requires an ISchemaRegistryEncoder; pass it as { srEncoder }
   ```

2. **Offset position.** A fresh group with `latest` only sees messages published
   *after* it joins. If the publish happened first, the consumer is idle by
   design. With `earliest`, it replays everything — including other encodings
   (entry 9).

3. **Topic subscription.** Is the topic in `TOPICS` / `CONSUMER_CHANNELS`? An
   event routed to `iam.tenant.created` is invisible to a consumer subscribed
   only to `iam.user.registered`.

4. **Group membership.** Another instance in the same group may hold the
   partitions. Duplicate workers are easy to leave running:

   ```bash
   ps aux | grep -E "ews_worker|dist/main.js" | grep -v grep
   ```

5. **Handler, not delivery.** `No handler found for event type: …` means the
   message *did* arrive and decode — nothing is registered to act on it.

---

## Reading the outbox

The outbox is the authority on whether a publish happened:

```text
Outbox metrics: {'total_events_published': 3, 'total_events_failed': 0, …}
Outbox stats:   {'pending': 0, 'processing': 0, 'published': 1182, 'failed': 6, …}
```

`pending` climbing means publishes are failing — the error is logged next to the
event id. Rows stay pending and retry, so a fixed bug drains the backlog on the
next poll, and a `pub` count higher than expected is usually an older backlog
draining rather than duplicate events from this run.
