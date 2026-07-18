# CommonRestClient — reference

A convenient, framework-agnostic async REST client.

- **Source:** [`rest_client.py`](./rest_client.py)
- **Tests:** [`tests/unit_local/test_rest_client.py`](../../../../tests/unit_local/test_rest_client.py)
- **Backend:** `httpx.AsyncClient` by default, swappable via the `RestTransport` protocol.

## Why

- One method per HTTP verb + a generic `request()`.
- Pluggable authentication (Bearer, API key, Basic, custom headers).
- **Decoupled from `httpx`** — callers only ever see `RestResponse` and the
  `RestTransport` protocol, so the HTTP library can be replaced without touching
  call sites.
- msgspec-native JSON: request bodies encode via `encode_json`, responses decode
  via `decode_json` (typed decoding into structs supported).

## Quick start

```python
from foundation.http.rest_client import CommonRestClient, BearerAuth

async with CommonRestClient(
    "https://api.example.com",
    auth=BearerAuth("my-token"),
    default_headers={"Accept": "application/json"},
    raise_for_status=True,          # non-2xx -> RestResponseError
) as client:
    res = await client.get("/users", params={"page": 1})
    users = res.json()

    created = await client.post("/users", json={"name": "Ada"})
    print(created.status_code, created.json())
```

## Client API

### Constructor

```python
CommonRestClient(
    base_url: str,
    *,
    auth: Auth | None = None,                 # default NoAuth()
    default_headers: Mapping[str, str] | None = None,
    default_params: Mapping[str, Any] | None = None,
    timeout: float = 10.0,                    # used only for the default transport
    pool: PoolConfig | None = None,           # connection pool; default transport only
    raise_for_status: bool = False,
    transport: RestTransport | None = None,   # default HttpxRestTransport
)
```

### Methods

| Method | Notes |
| --- | --- |
| `get / post / put / patch / delete / head / options(path, **kwargs)` | Verb shortcuts; forward to `request()`. |
| `request(method, path, *, params, json, data, content, headers, auth, timeout, raise_for_status)` | Core request. Returns `RestResponse`. |
| `build_url(path)` | Joins `path` onto `base_url`; passes absolute `http(s)://` URLs through unchanged. |
| `aclose()` | Closes the underlying transport. |
| `async with client:` | Auto-closes on exit. |

### `request()` arguments

- `path` — relative (resolved against `base_url`) **or** an absolute URL (bypasses `base_url`).
- `params` — query params; merged with `default_params` and auth params.
- `json` — any JSON-serializable value **or** `msgspec.Struct`; encoded and sent with
  `Content-Type: application/json`. Mutually exclusive with `data`/`content`.
- `data` — form body (`application/x-www-form-urlencoded`).
- `content` — raw `bytes` body.
- `headers` — per-request headers (**highest priority**).
- `auth` — per-request `Auth` override. `None` keeps the client default; pass
  `NoAuth()` to send one unauthenticated request.
- `timeout` — per-request timeout override (seconds).
- `raise_for_status` — per-request override of the client setting.

### Merge precedence

- **Headers:** `default_headers` → auth headers → JSON `Content-Type` (if `json` and not already set) → per-request `headers`.
- **Params:** `default_params` → auth params → per-request `params`.

## Authentication (`Auth` strategies)

An `Auth` contributes headers and/or query params. Set on the client and/or per request.

| Strategy | Effect |
| --- | --- |
| `NoAuth()` | Nothing. Use as a per-request override to disable the client default. |
| `BearerAuth(token, *, scheme="Bearer")` | `Authorization: Bearer <token>`. `token` may be a `str` **or** `Callable[[], str]` (re-evaluated per request → token refresh). |
| `ApiKeyAuth(key, *, header_name="X-API-Key", query_param=None)` | Key as a header, or as a query param when `query_param` is set. |
| `BasicAuth(username, password)` | `Authorization: Basic <base64>`. |
| `HeaderAuth({...})` | Arbitrary custom headers. |

Custom strategy — subclass `Auth` and override what you need:

```python
class HmacAuth(Auth):
    def headers(self) -> Mapping[str, str]:
        return {"X-Signature": compute_sig()}
```

## `RestResponse`

Neutral, frozen response wrapper (no `httpx` in the public surface).

| Member | Description |
| --- | --- |
| `status_code: int` | HTTP status. |
| `content: bytes` | Raw body. |
| `text -> str` | Body decoded with `encoding` (default utf-8, `errors="replace"`). |
| `json(as_type=None)` | Parsed body; pass a type/`msgspec.Struct`/dataclass for typed, validated decode. |
| `headers: Mapping[str, str]` | Response headers. |
| `get_header(name, default=None)` | Case-insensitive lookup. |
| `is_success / is_client_error / is_server_error` | 2xx / 4xx / 5xx checks. |
| `raise_for_status()` | Raises `RestResponseError` on 4xx/5xx; returns `self` on success (chainable). |
| `url`, `method`, `elapsed_seconds` | Final URL, verb, wall-clock time (if backend reports it). |

## Errors

```
RestClientError                     # base
├── RestConnectionError             # transport failure (DNS/refused/TLS); underlying error in __cause__
│   └── RestTimeoutError            # request timed out
└── RestResponseError               # 4xx/5xx when raise_for_status is in effect; .status_code, .response
```

Callers can handle failures without importing `httpx`.

## Connection pooling

`HttpxRestTransport` owns a **single, lazily-created `httpx.AsyncClient`** and reuses
it for every request, so TCP/TLS connections are pooled and kept alive across calls.
The pool is closed by `client.aclose()` or on `async with` exit.

Tune it with `PoolConfig` (backend-neutral; defaults mirror `httpx`):

```python
from foundation.http.rest_client import CommonRestClient, PoolConfig

client = CommonRestClient(
    "https://api.example.com",
    pool=PoolConfig(
        max_connections=200,            # total concurrent connections (None = unbounded)
        max_keepalive_connections=50,   # idle keep-alive conns retained (0 disables keep-alive)
        keepalive_expiry=30.0,          # seconds before an idle conn is closed (None = never)
        follow_redirects=True,
    ),
    timeout=15.0,
)
```

| `PoolConfig` field | Default | Meaning |
| --- | --- | --- |
| `max_connections` | `100` | Max concurrent connections; `None` = unbounded. |
| `max_keepalive_connections` | `20` | Max idle keep-alive connections kept for reuse; `0` disables keep-alive. |
| `keepalive_expiry` | `5.0` | Seconds an idle keep-alive connection lives; `None` = no expiry. |
| `follow_redirects` | `True` | Follow 3xx redirects transparently. |

`pool` (and `timeout`) apply **only to the default transport** — they are ignored when
you pass your own `transport=`.

**Advanced httpx options** (TLS `verify`, `http2`, `proxy`, `trust_env`, `cert`,
`event_hooks`, ...) are forwarded verbatim by constructing the transport directly:

```python
from foundation.http.rest_client import CommonRestClient, HttpxRestTransport, PoolConfig

transport = HttpxRestTransport(
    timeout=15.0,
    pool=PoolConfig(max_connections=200),
    verify="/etc/ssl/corp-ca.pem",   # any httpx.AsyncClient kwarg
    http2=True,
    trust_env=False,
)
client = CommonRestClient("https://api.example.com", transport=transport)
```

> Sharing one client (and thus one pool) across your app is preferred over creating a
> new `CommonRestClient` per request. Build it once and reuse it.

## Swapping the HTTP backend

Everything above `RestTransport.request()` (URL building, auth, header/param merge,
JSON handling, error translation) is backend-independent. To use another library,
implement the protocol and pass `transport=`:

```python
@runtime_checkable
class RestTransport(Protocol):
    async def request(self, method, url, *, headers=None, params=None,
                      content=None, data=None, timeout=None) -> RestResponse: ...
    async def aclose(self) -> None: ...
```

The default `HttpxRestTransport`:
- Owns a lazily-created, pooled `httpx.AsyncClient`.
- Translates `httpx.TimeoutException` → `RestTimeoutError`, `httpx.RequestError` → `RestConnectionError`.
- Accepts an injected `client=httpx.AsyncClient(...)` (used for tests / a pre-tuned
  client); it does **not** close a client it did not create.

## Subclassing for a concrete API

```python
class GithubClient(CommonRestClient):
    def __init__(self, token: str) -> None:
        super().__init__("https://api.github.com", auth=BearerAuth(token))

    async def get_repo(self, owner: str, repo: str) -> dict:
        res = await self.get(f"/repos/{owner}/{repo}")
        return res.raise_for_status().json()
```

## Testing

Two layers (see the test file):

1. **`RecordingTransport`** — a `RestTransport` fake that records calls and returns
   canned responses. Exercises URL building, verb dispatch, header/param merge, every
   auth strategy, JSON/form bodies, `raise_for_status`, lifecycle — no network.
2. **`httpx.MockTransport`** — drives `HttpxRestTransport` end-to-end: real `httpx`
   wiring, response conversion, and error translation.

```bash
uv run --package foundation pytest -v libs/foundation/tests/unit_local/test_rest_client.py
```

## Notes

- `httpx` is currently a **transitive** dependency (via `opentelemetry-instrumentation-httpx`)
  and is imported directly here and in [`http_client.py`](./http_client.py). To make it
  explicit, add `httpx>=0.28` to `libs/foundation/pyproject.toml` and run
  `uv sync --all-packages`.
- The existing `KeycloakAdminRestClient(CommonRestClient)` inherits the
  `base_url` / `build_url` surface unchanged.
```
