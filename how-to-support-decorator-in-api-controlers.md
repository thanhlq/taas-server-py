# How to support a new decorator in API controllers

A practical guide for adding a decorator (like `@instrument`, `@cache`,
`@ratelimit`) to framework-agnostic controllers and making it work through
**both** adapters: `libs/http_fastapi` and `libs/http_litestar`.

---

## 1. Background: how the layers fit together

```
libs/ews (business)         ──>  declares controllers using foundation.http
                                 (@get/@post, @cache, @instrument, ...)
                                       │
foundation.http               framework-agnostic route metadata + decorators
   ├─ decorator.py               @get/@post/@websocket → attach a Route to the fn
   ├─ route.py                   Route / WebSocketRoute / SocketIOHandler dataclasses
   ├─ controller.py              BaseController.get_routes() binds handlers to self
   └─ cache.py                   behavior decorator (@cache)
                                       │
                  ┌────────────────────┴────────────────────┐
libs/http_fastapi                              libs/http_litestar
   adapters/_controller.py                        adapters/_controller.py
   fastapi_msgspec/routing.py                     adapters/_dependencies.py
   → translate Route → FastAPI APIRoute           → translate Route → Litestar handler
```

The business layer (`libs/ews`) never imports a web framework. It only uses
`foundation.http`. Each adapter reads the framework-agnostic `Route` objects
and registers them with the real framework.

So when you add a decorator, the work is split:

- **foundation**: define the decorator (or its marker).
- **each adapter**: make sure the decorator survives signature introspection
  and behaves correctly.

---

## 2. Two kinds of decorators — know which one you are adding

### a) Route *marker* decorators (`@get`, `@post`, `@websocket`)

They **do not wrap** the function. They attach metadata via `setattr`:

```python
# foundation/http/decorator.py
setattr(func, ROUTE_ATTR, Route(...))   # "__platform_core_route__"
return func                              # SAME function object returned
```

`BaseController.get_routes()` later collects that metadata and rebinds the
handler to the instance with `meta.with_handler(getattr(self, name))`.

If your new decorator only needs to carry *configuration* (a new per-route
option), prefer this style: add a field to `Route` (`route.py`), set it in
`route()` (`decorator.py`), and read it in both adapters' `_add_route` /
`build_handler_for_route`. **No signature problems** because the function is
never wrapped.

### b) Behavior *wrapper* decorators (`@cache`, `@instrument`, `@ratelimit`)

They **replace** the function with a wrapper that runs extra logic around the
call. This is where things get tricky, because the adapters introspect the
handler's signature to build request models, and a wrapper can corrupt that
signature.

The rest of this guide is about (b).

---

## 3. The core pitfall: `functools.wraps` + bound methods leak `self`

Controller handlers are **methods**. `BaseController` binds them to the
instance (`getattr(self, name)`), so by the time an adapter sees the handler,
`self` should already be gone from the signature.

`@instrument` (and most wrapper decorators) use `functools.wraps`:

```python
@wraps(func_or_class)          # copies __dict__, sets __wrapped__
def wrapper(*args, **kwargs): ...
wrapper.__signature__ = inspect.signature(func_or_class)   # ← includes self!
```

Two side effects bite the adapters:

1. **`__wrapped__`** is set → `inspect.signature(...)` will *follow the chain*
   back to the original **unbound** function (which still has `self`).
2. **`__signature__`** is pinned to the unbound signature → it includes `self`.

For a *bound* method these usually cancel out (Python strips the first arg).
But the moment an adapter re-wraps the handler with **another**
`functools.wraps`, the stale `__signature__` (with `self`) gets **copied onto
a plain function**, where `self` is no longer stripped. The framework then
treats `self` as a required request parameter.

> Real symptom we hit: FastAPI returned
> `422 {"loc": ["query", "self"], "msg": "Field required"}` for an
> `@instrument` handler whose return type was a `msgspec.Struct`
> (`Project | ErrorResponse`). It only triggered for struct/union returns,
> because that path re-wrapped the endpoint a second time.

### The golden rule

> **Whenever you wrap a handler inside an adapter, immediately re-pin a clean
> signature:** `wrapper.__signature__ = inspect.signature(original_handler)`.
> Never let `functools.wraps` alone decide the public signature of a handler
> the framework will introspect.

This is exactly why the Litestar adapter *deliberately avoids*
`functools.wraps` (see the comments in
`http_litestar/adapters/_dependencies.py` and `_controller.py`) and why the
FastAPI helpers set `__signature__` explicitly.

---

## 4. Case study: how `@instrument` was supported

`@instrument` is defined in
`foundation/observability/opentelemetry/decorator.py` and resolved through
`foundation/observability/factory.py` (real OTEL impl when tracing is
enabled, a no-op otherwise). The business side just writes:

```python
@get(path='/error-trace')
@instrument()                       # runs first, wraps the function
def get_project_error_trace(self) -> Project | ErrorResponse:
    ...
```

(`@instrument` is *below* `@get`, so it wraps the function first; then `@get`
attaches the `Route` metadata to the instrument wrapper.)

### Litestar — already worked, no change

`adapt_handler` / `_make_wrapper` rebuild a clean signature and never call
`functools.wraps`, so the stale `self` never propagates.

### FastAPI — needed one fix

The leak was in `fastapi_msgspec/routing.py → MsgSpecRoute._wrap_endpoint`.
When the return type contains a `msgspec.Struct`, it re-wraps the endpoint to
encode the response — and that `functools.wraps(endpoint)` copied the stale
`self` signature. The fix re-pins the clean bound signature:

```python
def _wrap_endpoint(endpoint):
    clean_sig = inspect.signature(endpoint)   # bound method → self stripped
    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def async_wrapper(*args, **kwargs) -> Response:
            ...
        async_wrapper.__signature__ = clean_sig   # ← override stale signature
        return async_wrapper
    @functools.wraps(endpoint)
    def sync_wrapper(*args, **kwargs) -> Response:
        ...
    sync_wrapper.__signature__ = clean_sig         # ← override stale signature
    return sync_wrapper
```

Its sibling `_rewrite_struct_params` already did this (it sets
`__signature__ = new_sig`), which is why struct *parameters* were fine but the
struct *return* path was not.

---

## 5. Where each concern is handled today (reference map)

| Concern | FastAPI adapter | Litestar adapter |
|---|---|---|
| Route registration | `adapters/_controller.py: _add_route` | `adapters/_controller.py: build_handler_for_route` |
| Clean signature / strip `self` | `_retarget_cache_injected_params` | `_dependencies.py: adapt_handler` / `_make_wrapper` |
| `@cache` injected `request`/`response` | `_retarget_cache_injected_params` (reads `RequestLike`/`ResponseLike`) | `adapt_handler` (reads `__cache_injected_params__`) |
| `@ratelimit` | `_apply_rate_limit` (synthesises `request: Request`) | `build_handler_for_route` + `rate_limit_guard` |
| `Context` injection | rewrite to `Depends(get_request_context)` | `Provide(get_request_context)` |
| msgspec.Struct body/return | `fastapi_msgspec/routing.py: MsgSpecRoute` | native (Litestar speaks msgspec) |
| Response wrapping (re-wrap site!) | `_wrap_endpoint` | n/a |

Any place in this table that **wraps** the handler is a place your decorator's
signature must survive.

---

## 6. Checklist for adding a new wrapper decorator

1. **Define the decorator** in `foundation` (and, if it's optional
   infra like tracing, give it a no-op fallback in a factory).

2. **Decide marker vs wrapper** (§2). If config-only, add a `Route` field and
   skip most of the below.

3. **If it wraps the function**, make the wrapper robust:
   - After `functools.wraps`, set
     `wrapper.__signature__ = inspect.signature(wrapped)` so the public
     signature stays correct.
   - Pick the sync vs async wrapper using a coroutine check
     (`inspect.iscoroutinefunction`) so `async def` handlers stay async.
   - If you inject new parameters the handler didn't declare, record their
     names on an attribute (mirror `@cache`'s `__cache_injected_params__`) so
     adapters can strip them from the public signature.

4. **Verify both adapters introspect cleanly** — the failure mode is almost
   always a leaked `self` or a leaked injected param. Confirm the registered
   route exposes no spurious query/path params:

   ```python
   # FastAPI
   for r in app.routes:
       if getattr(r, "dependant", None):
           print(r.path, [p.name for p in r.dependant.query_params])  # expect []
   ```

5. **Test the matrix** (both frameworks) against a controller using your
   decorator. Cover the combinations that hit re-wrap sites:
   - sync and `async` handlers,
   - `dict` return **and** `msgspec.Struct` / union (`A | B`) return,
   - a `msgspec.Struct` body parameter,
   - combined with `@cache`, `@ratelimit`, and `Context` injection.

   For FastAPI a 422 mentioning `self` (or an injected param) means the
   signature leaked — re-pin it per §3.

6. **Confirm the behavior actually runs**, not just that routes return 200.
   For `@instrument` we asserted a span was recorded via an
   `InMemorySpanExporter`; do the equivalent for your decorator (cache hit,
   rate-limit 429, etc.).

---

## 7. TL;DR

- Controllers stay framework-agnostic; the adapters do the wiring.
- A wrapper decorator's **only real enemy is signature introspection**.
- Every time an adapter re-wraps a handler, it must
  `wrapper.__signature__ = inspect.signature(original)` — or avoid
  `functools.wraps` entirely (Litestar's approach).
- Test both adapters with struct/union returns, async, and body params, then
  verify the decorator's side effect actually happens.
