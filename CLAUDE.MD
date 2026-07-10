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
| libs/resiliant | Resilience utilities (e.g. transactional outbox pattern) |
| libs/slowapi_advanced | The rate limit library - allowing to use decorator as @rate_limit('5/minutes') which internally use the limits library |
| libs/store_memcached | Key/value store implementation using memcached |
| libs/store_redis | Key/value store implementation using redis |

### Applications (apps/)

| Project | Description |
| --- | --- |
| apps/ews_api | The ews api deployed using Fastapi (adapter: libs/http_fastapi) |
| apps/ews_api_litestar | The ews api deployed using Litestar (adapter: libs/http_litestar) |
| apps/ews_worker | Background worker for ews |

## Start the app

There are two scripts to start the api service in fastapi and litestar framework:

- start_ews_api_fastapi.sh: start the api service under fastapi framework
- start_ews_api_litestar.sh: start the api service under litestar framework
