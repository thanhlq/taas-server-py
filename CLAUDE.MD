# CLAUDE

## Projects

The is the uv workspace which include the following libraries, applications and services

### Libraries (libs/)

| Project | Description |
| --- | --- |
| libs/foundation | Contain all core definitions and common utils for building of application |
| libs/db | Contain all db models and migrations. |
| libs/ews | Core eworksuite business (ddd patterns): api definitions which can be used for building apps as: `ews_api` (Fastapi, adapter: libs/http_fastapi) and `ews_api_litestar` (Litestar, adapter: libs/http_litestar) |
| libs/banking_core | Banking domain core, including crypto factory/utilities |
| libs/block-kaspa | Kaspa blockchain integration: transactions, fee estimation and typed client |
| libs/http_fastapi | the Fastapi adatper for deploying of the api (i.e. ews) using Fastapi. |
| libs/http_litestar | the Fastapi adatper for deploying of the api (i.e. ews) using Litestar. |
| libs/iam | Contain iam implementation (with underline platform as Keycloak) but maximum Oauth 2.1 and OIDC compatible |
| libs/iam_keycloak | The iam implementation using Keycloak |
| libs/messaging_faststream | FastStream messaging utilities |
| libs/messaging_kafka | Kafka messaging utilities |
| libs/resiliant | Resilience implementations - the purpose is to implement best service patterns that can cover key features of Temporal.io |
| libs/slowapi_advanced | The rate limit library - allowing to use decorator as @rate_limit('5/minutes') which internally use the limits library |
| libs/store_memcached | Key/value store implementation using memcached |
| libs/store_redis | Key/value store implementation using redis |

### Applications (apps/)

| Project | Description |
| --- | --- |
| apps/ews_api | The ews api deployed using Fastapi (adapter: libs/http_fastapi) |
| apps/ews_api_litestar | The ews api deployed using Litestar (adapter: libs/http_litestar) |
| apps/ews_worker | Background worker for ews |

## Rules



## Conventions

- In each implementation, if there is factory.py then this file should be the entry point for building of the implemented services in this folder.

## Start the app

There are two scripts to start the api service in fastapi and litestar framework:

- start_fastapi_ews_api.sh: start the api service under fastapi framework
- start_litestar_ews_api.sh: start the api service under litestar framework

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

