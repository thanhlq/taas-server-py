# Signup stability soak (k6)

Long-running stress test for the **user signup** pipeline
(`POST /api/v1/auth/signup` → Keycloak → outbox → worker). The goal is to prove
the system stays healthy for 1–2 hours under a steady, sustainable load, and to
capture **CPU / RAM** of the three app processes (api, worker, outbox) so you
can spot memory leaks or latency drift.

## Files

| File | What it does |
| --- | --- |
| `stress-signup.js` | The k6 test. Sends signups back-to-back (`constant-vus`). All knobs are env vars. |
| `monitor-resources.sh` | Samples CPU% + RSS(MB) of api / worker / outbox into a CSV and prints a min/avg/max/last summary on exit. |
| `run-soak.sh` | Orchestrator: starts the monitor, runs k6, then prints one combined **final report** (k6 summary + resource summary). Use this. |
| `test_register_new_user.py` | The original single-request Python sample this test is based on. |

## Prerequisites

1. Infra up (Postgres 5432, Kafka 9092, Redis 6379) — already provided by the
   local docker compose stacks.
2. The three services running (each in its own terminal, from the repo root
   `taas-server-py/`):
   ```bash
   ./start_fastapi_ews_api.sh    # api    -> :8191   (python -m ews_api)
   ./start_outbox.sh             # outbox           (python -m outbox_worker)
   ./start_worker.sh             # worker           (python -m ews_worker)  SIGNUP_TEST_MODE=true
   ```
   `SIGNUP_TEST_MODE=true` is what lets the same signup be replayed forever:
   the signup flow deletes any existing org + user with the same name/email
   before recreating them, so the DB stays bounded.
3. `k6` installed (`k6 version`).

## Quick start

```bash
cd apps/ews_api/tests/performance_test/k6/test-signup-user

# 20s smoke test — confirm everything is wired up and green
VUS=1 DURATION=20s ./run-soak.sh

# the real 2-hour soak (leave it running)
VUS=1 DURATION=2h ./run-soak.sh
```

Every run writes to `runs/<timestamp>/`:
- `k6-output.log` — full k6 output + end-of-test summary
- `resource-usage.csv` — one row every `INTERVAL`s: `timestamp,api_cpu,api_mem_mb,worker_cpu,worker_mem_mb,outbox_cpu,outbox_mem_mb`
- `monitor.log` — live monitor output + the final resource table

At the end you get a single **FINAL REPORT** with the k6 pass/fail summary and
the CPU/RAM min/avg/max/last for each service.

## Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `VUS` | `1` | Concurrency = number of signups in flight. **See the concurrency note below.** |
| `DURATION` | `2h` | Test length (`30s`, `10m`, `2h`, …). |
| `INTERVAL` | `5` | Seconds between resource samples (`run-soak.sh` / monitor). |
| `EMAIL_MODE` | `per-vu` | `per-vu` (one stable email/org per VU, dedup keeps DB bounded), `fixed` (one email — the sample's), `unique` (brand-new every iteration, grows the DB). |
| `BASE_URL` | `http://localhost:8191` | API base URL. |
| `SIGNUP_EMAIL` | `ngocle1401@gmail.com` | Email used when `EMAIL_MODE=fixed`. |
| `OTP` | `807689` | Fixed test OTP. |
| `EMAIL_DOMAIN` | `example.com` | Domain for generated emails. |

Run k6 directly (without the monitor) if you prefer:
```bash
VUS=1 DURATION=2h k6 run stress-signup.js
```

## ⚠️ Concurrency note — keep `VUS=1` for a stability soak

A single signup is a **multi-step Keycloak flow**: create organization → set
its domain → create user → add the user as an org member. That flow is **not
robust to running in parallel with itself**. With `VUS>=2` you get a steady
**~8–20% of `5xx`** responses, regardless of the email/org strategy:

- `400 Domain <slug> is already linked to another organization`
- `404 Organization not found.`

These come from Keycloak **eventual-consistency races** between the org create /
delete / member steps — not from the test. At `VUS=1` the flow is serialized and
the run is **100% clean**, which is exactly what you want for a leak/stability
soak (a clean baseline, so any error or drift that appears *is* the signal).

> If you *want* to probe that concurrency weakness, run `VUS=2` / `VUS=5` and
> watch `http_req_failed` — that is a genuine finding worth fixing in the org
> creation flow (e.g. make it idempotent / retry on the consistency errors),
> not a limitation of this test.

Throughput at `VUS=1` is ~0.7 signups/s (~45/min, ~2,700/hr) given the ~1.3–1.6s
per-signup latency — plenty for a stability soak over 1–2 hours.

### Org-name gotcha (already handled in the script)

The app derives the Keycloak org **domain** from the org name via
`generate_saas_subdomain(name, max_length=12)` — lowercased, non-alnum dropped,
then **truncated to 12 chars**. Two org names sharing the same first 12 chars
collide on the domain. The script therefore uses short org names with the
distinguishing id at the front (`vu1-o`, `vu2-o`, … / base36 for `unique`), and
never puts `@` in an org name (Keycloak rejects it).

## How resource monitoring works

`monitor-resources.sh` matches each service by the module its `.venv` python
runs and **sums CPU%/RSS across all matching processes** (so `--reload` children
are counted):

- api → `-m ews_api`
- worker → `-m ews_worker`
- outbox → `-m outbox_worker`

CPU% is macOS `ps` recent-usage and is **per core** (a busy multi-threaded
process can read >100%; this host has `sysctl hw.ncpu` cores, shown in the
summary header). RSS is resident memory in MB. For a leak, watch whether
`*_mem_MB` **max/last** keep climbing across the run vs. staying flat.

## Reading the result

- **PASS** (`http_req_failed rate<0.01`, `signup_ok rate>0.99`,
  `p(95)<8000ms`): the pipeline held up.
- **FAIL**: inspect `runs/<ts>/k6-output.log` — every non-200 logs
  `FAIL status=… body=…` with the real reason, and cross-reference the service
  logs.
- **Memory leak**: open `runs/<ts>/resource-usage.csv` and plot `*_mem_mb`; a
  steady upward slope over 1–2h is a leak, a flat/sawtooth line is healthy.
