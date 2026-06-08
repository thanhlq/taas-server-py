# Project

The fastapi adapters so that the api as ews_api (apps/ews_api) can easily switch to fastapi instead of litestar

This implementation should be maxium compatible with litestar (https://github.com/litestar-org/litestar) and saple fullstack project (https://github.com/litestar-org/litestar-fullstack)

Fastapi adapters: the main implementation is in libs/http_fastapi/src/http_fastapi/adapters which for loading of user defined api controller (routes, handlers, rate limit, cache,...) and load into Fastapi api framework.
