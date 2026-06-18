"""
The purpose

- The test is to measure the following serialization scenarios (config key: MESSAGE_ENCODING):
    1. json: JSON serialization of a BaseEvent dict (with a large nested dict payload)
    2. msgpack: Msgpack serialization of a BaseEvent dict (with a large nested dict payload)
    3. schema-registry-avro: Avro serialization of a BaseEvent dict (with a large nested dict payload)
- The configuration is in libs/core/src/core/conf/settings.py, the variable: MESSAGE_ENCODING
- Each scenario is implemented as a separate test function and the benchmark
  result is printed to the console.  After all scenarios complete, a summary
  table is printed showing relative size / latency / throughput vs the JSON
  baseline.
- The same flat ``UserDirectoryCreatedEvent`` is used for every scenario, with
  a ~3 KB nested dict assigned to its ``payload`` field so the encoders are
  exercised on realistic, non-trivial input.
- For Avro, dict-valued fields are msgpack-packed before encoding (matching the
  production behaviour of ``MsgEncoder.serialize_dict_fields_to_bytes``) since
  Avro has no native arbitrary-map type.
- Can refer to some test implementations in libs/messaging_faststream/tests/unit
- To run the benchmark, execute:
    uv run pytest libs/messaging_faststream/tests/benchmark/message_serialization_benchmark.py -s
    uv run pytest libs/messaging_faststream/tests/benchmark/message_serialization_benchmark.py -s 2>&1 | tail -80
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

# import msgpack
import pytest

# ---------------------------------------------------------------------------
# Path setup — make `core` and `messaging_faststream` importable when this
# file is run directly (mirrors the pattern used in the unit tests).
# ---------------------------------------------------------------------------

_repo_root = Path(__file__).parent.parent.parent.parent.parent
_core_src = _repo_root / 'libs' / 'core' / 'src'
_fs_src = Path(__file__).parent.parent.parent / 'src'

for _p in (_core_src, _fs_src):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ITERATIONS = 10_000
SCHEMA_REGISTRY_URL = 'http://localhost:8081'
TEST_TOPIC = 'iam.user.benchmark'

# Module-level result store — populated by each test, consumed by the
# summary fixture that runs after the whole module is finished.
_RESULTS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _schema_registry_available() -> bool:
    """Return ``True`` when the local Schema Registry responds on port 8081."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f'{SCHEMA_REGISTRY_URL}/subjects')
            return r.is_success
    except Exception:
        return False


def _build_big_payload_dict() -> dict:
    """A representative ~3 KB payload — multiple nested objects, lists, and primitives."""
    return {
        'user': {
            'id': 'usr_abc123def456',
            'email': 'alice@example.com',
            'username': 'alice',
            'first_name': 'Alice',
            'last_name': 'Anderson',
            'phone': '+1-555-0100',
            'avatar_url': 'https://cdn.example.com/avatars/alice-anderson-01.png',
            'birth_date': '1990-05-15',
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2026-05-01T12:34:56Z',
            'is_verified': True,
            'is_active': True,
            'locale': 'en-US',
        },
        'tenant': {
            'id': 'tnt_acme',
            'name': 'Acme Corp',
            'domain': 'acme.example.com',
            'plan': 'enterprise',
            'seats': 500,
            'created_at': '2023-06-15T00:00:00Z',
        },
        'roles': [
            {'id': 'role_admin', 'name': 'Administrator', 'tenant_id': 'tnt_acme'},
            {'id': 'role_user', 'name': 'User', 'tenant_id': 'tnt_acme'},
            {'id': 'role_finance', 'name': 'Finance', 'tenant_id': 'tnt_acme'},
            {'id': 'role_audit', 'name': 'Auditor', 'tenant_id': 'tnt_acme'},
        ],
        'permissions': [
            f'perm.{module}.{action}'
            for module in ('user', 'tenant', 'billing', 'audit', 'report', 'asset')
            for action in ('read', 'write', 'delete', 'admin')
        ],
        'settings': {
            'language': 'en-US',
            'timezone': 'America/Los_Angeles',
            'date_format': 'YYYY-MM-DD',
            'time_format': 'HH:mm:ss',
            'currency': 'USD',
            'theme': 'dark',
            'notifications': {
                'email': True,
                'sms': False,
                'push': True,
                'in_app': True,
            },
            'feature_flags': {
                'beta_dashboard': True,
                'experimental_search': False,
                'ai_assistant': True,
                'advanced_analytics': True,
                'realtime_alerts': True,
            },
        },
        'audit': {
            'last_login_at': '2026-05-04T22:15:30Z',
            'last_login_ip': '203.0.113.42',
            'last_login_ua': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            ),
            'failed_login_attempts': 0,
            'mfa_enabled': True,
            'mfa_methods': ['totp', 'webauthn'],
            'session_count': 3,
        },
        'metadata': {
            'source': 'iam-service',
            'pipeline_version': '2.4.1',
            'schema_version': 1,
            'tags': ['benchmark', 'serialization', 'performance', 'large-payload'],
            'notes': (
                'This payload is intentionally sized to exercise the encoders '
                'with realistic nested data — multiple objects, lists of strings, '
                'and a few primitive scalars per top-level key. '
            ) * 4,
        },
    }


def _build_sample_dict() -> dict:
    """Return a flat ``BaseEvent`` dict with the big payload assigned to ``payload``.

    The dataclass field ``payload`` is annotated ``bytes | str | None``; we set
    it on the resulting dict (not the dataclass) so every encoder under test
    sees a real nested dict either natively (json/msgpack) or after the
    production msgpack-pack pre-step (Avro).
    """
    from core.iam.events.iam_constants import IamEvents
    from core.iam.events.iam_events import UserDirectoryCreatedEvent

    event = UserDirectoryCreatedEvent(
        event_type=IamEvents.USER_DIRECTORY_CREATED.value,
        email='alice@example.com',
        username='alice',
        realm_name='master',
        tenant=None,
    )
    sample = event.as_dict()
    sample['payload'] = _build_big_payload_dict()
    return sample


# ---------------------------------------------------------------------------
# Stats / reporting
# ---------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float:
    """Return the *q*-percentile (0..1) of *values* using nearest-rank."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(q * len(s))) - 1))
    return s[idx]


def _pct(value: float, baseline: float) -> str:
    """Signed percentage of *value* relative to *baseline* (formatted ``+12.3%``)."""
    if baseline == 0:
        return '   n/a'
    return f'{(value - baseline) / baseline * 100.0:+6.1f}%'


def _ratio(faster: float, slower: float) -> str:
    """Speed/size ratio for the small/large pair (``slower`` is the numerator)."""
    if faster == 0:
        return 'n/a'
    return f'{slower / faster:.2f}x'


def _record(name: str, encode_us: list[float], decode_us: list[float], encoded_size: int) -> None:
    """Cache benchmark results for the end-of-module summary."""
    _RESULTS[name] = {
        'encode_us': encode_us,
        'decode_us': decode_us,
        'size': encoded_size,
        'encode_avg': sum(encode_us) / len(encode_us),
        'decode_avg': sum(decode_us) / len(decode_us),
    }


def _print_scenario(name: str, baseline_name: str | None = None) -> None:
    """Print a detailed report for a single scenario, with comparisons."""
    data = _RESULTS[name]
    enc, dec = data['encode_us'], data['decode_us']
    n = len(enc)
    enc_avg, dec_avg = data['encode_avg'], data['decode_avg']

    print()
    print(f'━━━━━━━━━━ {name} ━━━━━━━━━━')
    print(f'  iterations         : {n:>10,}')

    if baseline_name is None or baseline_name == name:
        print(f'  encoded size       : {data["size"]:>10,} bytes   (baseline)')
        print(f'  encode avg         : {enc_avg:>10.2f} µs      (baseline)')
        print(f'  decode avg         : {dec_avg:>10.2f} µs      (baseline)')
    else:
        b = _RESULTS[baseline_name]
        size_pct = _pct(data['size'], b['size'])
        size_ratio = _ratio(data['size'], b['size']) if data['size'] < b['size'] else _ratio(b['size'], data['size'])
        size_dir = 'smaller' if data['size'] < b['size'] else 'larger '
        enc_pct = _pct(enc_avg, b['encode_avg'])
        dec_pct = _pct(dec_avg, b['decode_avg'])
        enc_ratio = _ratio(enc_avg, b['encode_avg']) if enc_avg < b['encode_avg'] else _ratio(b['encode_avg'], enc_avg)
        dec_ratio = _ratio(dec_avg, b['decode_avg']) if dec_avg < b['decode_avg'] else _ratio(b['decode_avg'], dec_avg)
        enc_dir = 'faster ' if enc_avg < b['encode_avg'] else 'slower '
        dec_dir = 'faster ' if dec_avg < b['decode_avg'] else 'slower '
        print(
            f'  encoded size       : {data["size"]:>10,} bytes   '
            f'({size_pct} vs {baseline_name}, {size_ratio} {size_dir})'
        )
        print(
            f'  encode avg         : {enc_avg:>10.2f} µs      '
            f'({enc_pct} vs {baseline_name}, {enc_ratio} {enc_dir})'
        )
        print(
            f'  decode avg         : {dec_avg:>10.2f} µs      '
            f'({dec_pct} vs {baseline_name}, {dec_ratio} {dec_dir})'
        )

    enc_p50 = _percentile(enc, 0.50)
    enc_p95 = _percentile(enc, 0.95)
    enc_p99 = _percentile(enc, 0.99)
    dec_p50 = _percentile(dec, 0.50)
    dec_p95 = _percentile(dec, 0.95)
    dec_p99 = _percentile(dec, 0.99)
    enc_min, enc_max = min(enc), max(enc)
    dec_min, dec_max = min(dec), max(dec)
    enc_std = statistics.pstdev(enc)
    dec_std = statistics.pstdev(dec)

    print(f'  encode p50/p95/p99 : {enc_p50:>10.2f} / {enc_p95:>8.2f} / {enc_p99:>8.2f} µs')
    print(f'  encode min/max/σ   : {enc_min:>10.2f} / {enc_max:>8.2f} / {enc_std:>8.2f} µs')
    print(f'  decode p50/p95/p99 : {dec_p50:>10.2f} / {dec_p95:>8.2f} / {dec_p99:>8.2f} µs')
    print(f'  decode min/max/σ   : {dec_min:>10.2f} / {dec_max:>8.2f} / {dec_std:>8.2f} µs')
    print(
        f'  throughput         : encode {1e6 / enc_avg:>10,.0f} ops/s | '
        f'decode {1e6 / dec_avg:>10,.0f} ops/s'
    )


def _print_summary() -> None:
    """Print a comparison table across every recorded scenario."""
    if not _RESULTS:
        return

    baseline_name = 'json' if 'json' in _RESULTS else next(iter(_RESULTS))
    b = _RESULTS[baseline_name]

    print()
    print(f'═══════════════ Summary (baseline = {baseline_name}) ═══════════════')
    header = (
        f'{"format":<22} '
        f'{"size":>9} {"Δsize":>9}  '
        f'{"enc µs":>8} {"Δenc":>8}  '
        f'{"dec µs":>8} {"Δdec":>8}  '
        f'{"enc ops/s":>12} {"dec ops/s":>12}'
    )
    print(header)
    print('-' * len(header))

    for name, data in _RESULTS.items():
        size = data['size']
        enc_avg = data['encode_avg']
        dec_avg = data['decode_avg']
        if name == baseline_name:
            d_size = '  (base)'
            d_enc = '  (base)'
            d_dec = '  (base)'
        else:
            d_size = _pct(size, b['size'])
            d_enc = _pct(enc_avg, b['encode_avg'])
            d_dec = _pct(dec_avg, b['decode_avg'])
        print(
            f'{name:<22} '
            f'{size:>9,} {d_size:>9}  '
            f'{enc_avg:>8.2f} {d_enc:>8}  '
            f'{dec_avg:>8.2f} {d_dec:>8}  '
            f'{1e6 / enc_avg:>12,.0f} {1e6 / dec_avg:>12,.0f}'
        )
    print('=' * len(header))


@pytest.fixture(scope='module', autouse=True)
def _summary_after_all():
    """Print the cross-scenario summary table after every test in the module."""
    yield
    _print_summary()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_benchmark_json() -> None:
    """Scenario 1 — JSON serialization round-trip (handles nested dicts natively)."""
    sample = _build_sample_dict()
    encode_us: list[float] = []
    decode_us: list[float] = []
    encoded_size = 0

    for _ in range(ITERATIONS):
        t0 = time.perf_counter_ns()
        raw = json.dumps(sample).encode('utf-8')
        t1 = time.perf_counter_ns()
        json.loads(raw.decode('utf-8'))
        t2 = time.perf_counter_ns()
        encode_us.append((t1 - t0) / 1000.0)
        decode_us.append((t2 - t1) / 1000.0)
        encoded_size = len(raw)

    _record('json', encode_us, decode_us, encoded_size)
    _print_scenario('json', baseline_name=None)


def test_benchmark_msgpack() -> None:
    """Scenario 2 — Msgpack serialization round-trip (handles nested dicts natively)."""
    sample = _build_sample_dict()
    encode_us: list[float] = []
    decode_us: list[float] = []
    encoded_size = 0

    for _ in range(ITERATIONS):
        t0 = time.perf_counter_ns()
        raw = msgpack.packb(sample)
        t1 = time.perf_counter_ns()
        msgpack.unpackb(raw, raw=False)
        t2 = time.perf_counter_ns()
        encode_us.append((t1 - t0) / 1000.0)
        decode_us.append((t2 - t1) / 1000.0)
        encoded_size = len(raw)

    _record('msgpack', encode_us, decode_us, encoded_size)
    _print_scenario('msgpack', baseline_name='json')


@pytest.mark.asyncio
async def test_benchmark_schema_registry_avro() -> None:
    """Scenario 3 — Confluent Schema Registry + Avro round-trip.

    Avro has no arbitrary-map type, so dict-valued fields are msgpack-packed
    before encoding (and unpacked after decoding) — this matches the
    production path in ``MsgEncoder``.
    """
    if not await _schema_registry_available():
        pytest.skip(f'Confluent Schema Registry not reachable at {SCHEMA_REGISTRY_URL}')

    from core.iam.events.iam_events import UserDirectoryCreatedEvent
    from core.messaging.sr.schema_registry_fast import (
        SchemaRegistryEncoder,
        SchemaRegistryConfig,
    )

    schema = UserDirectoryCreatedEvent.avro_schema_to_python()
    encoder = SchemaRegistryEncoder(
        registry_config=SchemaRegistryConfig(url=SCHEMA_REGISTRY_URL),
        avro_schemas={TEST_TOPIC: schema},
    )

    sample = _build_sample_dict()

    def _avro_prep(d: dict) -> dict:
        return {k: msgpack.packb(v) if isinstance(v, dict) else v for k, v in d.items()}

    def _avro_post(d: dict) -> dict:
        return {k: msgpack.unpackb(v, raw=False) if isinstance(v, bytes) else v for k, v in d.items()}

    # Warm-up: registers the schema and primes the schema-id cache so the
    # first measured iteration is not skewed by an HTTP round-trip.
    raw_warm = await encoder.encode_event(TEST_TOPIC, _avro_prep(sample))
    _avro_post(await encoder.decode(TEST_TOPIC, raw_warm))

    encode_us: list[float] = []
    decode_us: list[float] = []
    encoded_size = 0

    for _ in range(ITERATIONS):
        t0 = time.perf_counter_ns()
        prepared = _avro_prep(sample)
        raw = await encoder.encode_event(TEST_TOPIC, prepared)
        t1 = time.perf_counter_ns()
        decoded = await encoder.decode(TEST_TOPIC, raw)
        _avro_post(decoded)
        t2 = time.perf_counter_ns()
        encode_us.append((t1 - t0) / 1000.0)
        decode_us.append((t2 - t1) / 1000.0)
        encoded_size = len(raw)

    _record('schema-registry-avro', encode_us, decode_us, encoded_size)
    _print_scenario('schema-registry-avro', baseline_name='json')
