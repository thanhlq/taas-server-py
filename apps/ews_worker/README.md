# ews_worker

Background worker for eWorkSuite. Built on `foundation.worker.BaseWorker` (the
worker-side counterpart to the API's `BaseApiApplication`), it runs:

- a **Redis cache** service (same wiring as `ews_api`),
- the **FastStream Kafka** messaging service (`messaging_faststream`),
- one or more **event subscribers** (a demo `ews.demo.ping` subscriber ships by
  default), and
- an optional **transactional-outbox relay** (built on the `resiliant` outbox),
  enabled with `OUTBOX_POLLER_ENABLE=true`.

A small aiohttp **health server** exposes `GET /health`.

## Layout

| File | Responsibility |
| --- | --- |
| `bootstrap.py` | Environment + settings + logging setup (mirrors `ews_api.bootstrap`) |
| `worker.py` | `EwsWorker(BaseWorker)` — cache, messaging, subscribers, tasks |
| `main.py` / `__main__.py` | Entry point (`ews_worker.main:main`) |

## Run

Requires Kafka, Redis, and Postgres to be up (see `docker-compose.yml`).

```bash
# from the repo root
./start_ews_worker.sh                 # uses .env
ENV_FILE=.env.test ./start_ews_worker.sh
```

Config via environment:

- `KAFKA_BOOTSTRAP_SERVERS` (default `localhost:9092`)
- `WORKER_LISTEN_PORT` (health server; default `7100` — avoids macOS AirPlay on 7000)
- `OUTBOX_POLLER_ENABLE` (default `false`)

## Test the messaging path (API ⇆ worker)

The worker subscribes to `ews.demo.ping`. Publish to it from any producer (the
API uses the same `IMessagingService.publish`) and the worker logs
`📥 [demo] received event ...`.

Integration test (skips automatically when Kafka is unreachable):

```bash
uv run --package ews_worker pytest apps/ews_worker/tests/integration
```

## Notes

- Domain (IAM/EWS) event handlers are not registered yet — they still live in
  the legacy `core.*` package and are pending migration. Register them in
  `EwsWorker._register_subscribers()` once available.
- `EventProcessorFast` and the `MessagingFactory` also still depend on `core.*`
  and are intentionally not used by the worker yet.
