# CLAUDE

## Projects

The is the uv workspace which include the following libraries, applications and services

### Libraries (libs/)

| Project | Description |
| --- | --- |
| libs/foundation | Contain all core definitions and common utils for building of application |
| libs/db | Platform db models and the single Alembic migration tree (also migrates `resiliant.models`). |
| libs/ews | Core eworksuite business (ddd patterns): api definitions which can be used for building apps as: `ews_api` (Fastapi, adapter: libs/http_fastapi) and `ews_api_litestar` (Litestar, adapter: libs/http_litestar) |
| libs/banking_core | Banking domain core, including crypto factory/utilities |
| libs/blob_service | Tenant-based blob storage: `create_blob_service()` (adapter by `BLOB_STORAGE_PROVIDER`, tenant bucket in `taas_tenants.sys_settings.bucket`), memory adapter. Interfaces in `foundation.blob`. See `docs/developers/blob-storage-guide.md` |
| libs/blob_s3 | Blob adapter for S3 compatible storage: AWS S3, Cloudflare R2, RustFS (aiobotocore) |
| libs/blob_gcp | Blob adapter for Google Cloud Storage |
| libs/blob_azure | Blob adapter for Azure Blob Storage (aio + SAS) |
| libs/block-kaspa | Kaspa blockchain integration: transactions, fee estimation and typed client |
| libs/http_fastapi | the Fastapi adatper for deploying of the api (i.e. ews) using Fastapi. |
| libs/http_litestar | the Fastapi adatper for deploying of the api (i.e. ews) using Litestar. |
| libs/iam | Contain iam implementation (with underline platform as Keycloak) but maximum Oauth 2.1 and OIDC compatible |
| libs/iam_keycloak | The iam implementation using Keycloak |
| libs/messaging_faststream | FastStream messaging utilities |
| libs/messaging_kafka | Kafka messaging utilities |
| libs/resiliant | All resilience implementations, settings and models (outboxes per use case, DLQ, idempotency on Postgres or Redis, saga, schedule, retry, circuit breaker, …) — covers key features of Temporal.io; `foundation.resiliant` keeps definitions only. See `docs/developers/resiliant-*.md` |
| libs/slowapi_advanced | The rate limit library - allowing to use decorator as @rate_limit('5/minutes') which internally use the limits library |
| libs/store_memcached | Key/value store implementation using memcached |
| libs/store_redis | Key/value store implementation using redis |

### Applications (apps/)

| Project | Description |
| --- | --- |
| apps/ews_api | The ews api deployed using Fastapi (adapter: libs/http_fastapi) |
| apps/ews_api_litestar | The ews api deployed using Litestar (adapter: libs/http_litestar) |
| apps/ews_worker | Background worker for ews |
| apps/outbox_worker | Outbox relay: one poller per outbox table + scheduler (`start_outbox.sh`, health port 7110) |

## Rules



## Conventions

- In each implementation, if there is factory.py then this file should be the entry point for building of the implemented services in this folder.

## Start the app

There are two scripts to start the api service in fastapi and litestar framework:

- start_fastapi_ews_api.sh: start the api service under fastapi framework
- start_litestar_ews_api.sh: start the api service under litestar framework

## Environment configuration

- Start from `cp .env.example .env`; each key is documented there with default, allowed values
  and whether it is required. Use `cp .env.test.example .env.test` only for local test overrides.
- `foundation.config.get_settings()` loads `ENV_FILE` or `.env` with `python-dotenv`; process
  environment variables take precedence. `.env.local` is not layered automatically.
- Keep real `.env` / `.env.test` gitignored. Check sync with
  `python3 ../taas-tools/env-check/check_env.py taas-server-py`.

### Local run gotchas (FastAPI EWS API — binds :8191)

- **Rate limiter Redis**: `RateLimitConfig.redis_host` defaults to `redis` (a docker-network
  name, unreachable from the host) and is wrapped as `redis://<host>:6379/0`, so it needs a
  BARE host. Locally run with `TAAS_RATE_LIMIT_REDIS_HOST=localhost bash start_fastapi_ews_api.sh`,
  otherwise every route returns `503 "Rate limit storage backend is unreachable"`.
- **CORS**: the FastAPI adapter installs `CORSMiddleware` in
  `libs/http_fastapi/.../configuration.py:configure_app` from `config.cors_config`. Allowed
  origins come from `.env` `ALLOWED_CORS_ORIGINS` and MUST include the scheme
  (`http://localhost:7101`). Browser SPA clients (web web-vite) need this; Next server-side
  fetches do not.
- **EWS controllers** are registered in `libs/ews/src/ews/__init__.py:get_ews_controllers`
  (`ppm.get_project_controllers` + `crm.get_crm_controllers` + `PlatformController`). CRM
  accounts live at `/api/v1/crm/accounts` (`libs/ews/src/ews/crm`). `CrmAccount` uses
  advanced_alchemy `SlugKey` → set a unique `slug` on create.
