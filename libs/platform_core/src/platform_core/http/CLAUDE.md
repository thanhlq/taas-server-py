# platform_core.http

I often use different web framework as fastapi, litestar for research, so I want:

- Use this module platform_core.http to allow register of rest api routes with configurations as:
  - controller (handler)
  - api path
  - permission
  - middleware
  - ....
- And then in the real http frameworks as fastapi (libs/http_fastapi) or litestar (libs/http_litestar) will implement the actually routes registration
- The real adapters implementated in libs/http_fastapi or libs/http_litestar will help the api projects as apps/ews_api can easily switch betwen these api frameworks.
- The ews project (libs/ews) is the core business, This project will not be dependent on any api frameworks instead of that it use platform_core.http for registration of api routes and in the real api projects as apps/ews_api will be responsible for wire up of the route difinitions with real api framework as fastapi or litestar
