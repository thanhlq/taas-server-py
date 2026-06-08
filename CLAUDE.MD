# CLAUDE

## Projects

The purpose is to build

### libs/platform_core

Contain all core definitions and common utils for building of application

### libs/db

Contain all db models and migrations.

### libs/ews

Core eworksuite business (ddd patterns): api definitions which can be used for building apps as:

- ews_api: the api using Fastapi (adater: libs/http_fastapi)
- ews_api_litestar: the api using Litestar (adater: libs/http_litestar)

### libs/http_fastapi

the Fastapi adatper for deploying of the api (i.e. ews) using Fastapi.

### libs/http_litestar

the Fastapi adatper for deploying of the api (i.e. ews) using Litestar.

### libs/iam

Contain iam implementation (with underline platform as Keycloak) but maximum Oauth 2.1 and OIDC compatible

### libs/slowapi_advanced

The rate limit library - allowing to use decorator as @rate_limit('5/minutes') which internally use the limits library

### libs/store_memcached

Key/value store implementation using memcached

### libs/store_redis

Key/value store implementation using redis
