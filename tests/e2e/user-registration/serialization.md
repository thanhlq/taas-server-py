# Serialization Guide

> **Scope:** The three supported message encodings, how to configure them, and
> what each puts on the wire.
>
> **Implemented in:** `taas-server-py/libs/foundation/src/foundation/messaging/utils/msg_encoder.py`

---

## Configuration

Two variables, set identically in **every** service that shares a topic —
`taas-server-py/.env`, `taas-server-js/.env`, and `floin-authorizer/.env`.

```bash
MESSAGE_ENCODING=schema-registry-avro   # schema-registry-avro | msgpack | json
MESSAGE_FIELD_ENCODING=msgpack          # msgpack | json  — Avro only
```

Defaults if unset: both are `msgpack`.

> Exported environment variables win over `.env` on both the Python and Node
> sides. Handy for one-off runs:
> `MESSAGE_ENCODING=json ./start_worker.sh`

`MessageEncodingType` also declares `avro-binary` and `protobuf`. Neither is
implemented — `protobuf` raises `NotImplementedError`. Only the three above work.

---

## The three encodings

| | `schema-registry-avro` | `msgpack` | `json` |
| --- | --- | --- | --- |
| Schema enforced | Yes, at publish | No | No |
| Registry needed | Yes | No | No |
| Size | Smallest | Small | Largest |
| Human-readable | No | No | Yes |
| Cross-language contract | Explicit, versioned | Structural only | Structural only |
| Silent field loss possible | No — guarded | No (nothing dropped) | No |
| Good for | Production, value-bearing events | Internal, high volume | Local debugging |

### Choosing

- **`schema-registry-avro`** for anything carrying value or crossing a team
  boundary. The schema is a checked contract, and evolution is tracked per event
  type. This is the only option where a field a consumer needs cannot silently
  vanish.
- **`msgpack`** when both sides are yours and you want compactness without
  registry infrastructure. No contract — a renamed field just arrives as a
  different key, and nothing notices until a consumer reads `undefined`.
- **`json`** for local work. Readable straight out of `kafka-console-consumer`.

---

## Wire format

### msgpack and json

The whole event dict, encoded. No header. `payload` stays a nested object.

```text
[ msgpack/json bytes of the entire event dict ]
```

### schema-registry-avro

Confluent wire format — a 5-byte header, then the Avro body:

```text
byte 0        bytes 1-4              bytes 5+
┌────────┬──────────────────┬─────────────────────────┐
│  0x00  │  schema_id (>I)  │  Avro-encoded record    │
└────────┴──────────────────┴─────────────────────────┘
  magic     big-endian u32     schemaless_writer output
```

Implemented in `sr/confluent.py` (`MAGIC_BYTE = 0x00`,
`WIRE_FORMAT_HEADER_SIZE = 5`). The embedded `schema_id` is how consumers resolve
the schema — see [avro-schema-registry.md](avro-schema-registry.md).

**`MESSAGE_FIELD_ENCODING` applies only here.** Avro has no arbitrary-key map
type that suits a free-form payload, so the nested `payload` object is
pre-encoded to bytes (msgpack or json) and carried as a single Avro field. It is
inert for the msgpack and json encodings, which nest naturally.

```python
# msg_encoder.py — Avro branch only
_msg_data[EVENT_PAYLOAD_FIELD] = self.encode_field(_event_payload)
```

Reading it back is `decode_field()`. A consumer that forgets this sees `payload`
as opaque bytes.

---

## Inspecting a message

```bash
# json — readable directly
kafka-console-consumer.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVERS" \
  --topic iam.user.registered --from-beginning --max-messages 1

# avro — first 5 bytes are the header; extract the schema id
#   od -An -tu1 -N5  →  0 0 0 0 6   means schema_id = 6
curl -s -u "$SR_USER:$SR_PASS" "$KAFKA_SCHEMA_REGISTRY_URL/schemas/ids/6" | jq -r .schema | jq
```

---

## Adding a new encoding

Three places must agree, or one side will publish what the other cannot read:

1. `MessageEncodingType` — add the value.
2. `MsgEncoder.encode_msg` / `decode_msg` — add the branch (Python).
3. The Node `MsgEncoder` equivalent in `taas-server-js/packages/foundation`.

Then run the full matrix (see [e2e-user-registration.md](e2e-user-registration.md)) —
a codec that works Python→Python can still fail Python→Node.
