# Project

The litestar adapters so that the api as ews_api (apps/ews_api) can easily switch to litestar instead of fastapi

Litestar adapters: the main implementation is in libs/http_litestar/src/http_litestar/adapters which for loading of user defined api controller (routes, handlers, rate limit, cache,...) and load into litestar api framework.
