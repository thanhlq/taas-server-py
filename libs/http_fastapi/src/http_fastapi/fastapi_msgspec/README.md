# fastapi msgspec integration

Make FastAPI work with [`msgspec.Struct`](https://jcristharif.com/msgspec/)
response models while still producing a correct OpenAPI document.

## Modules

| File | Purpose |
|---|---|
| `responses.py` | `MsgSpecJSONResponse` — `JSONResponse` whose `render()` uses `msgspec.json.encode`. |
| `requests.py`  | `MSGSpecJSONRequest` — `Request` whose `json()` uses `msgspec.json.decode`. |
| `routing.py`   | `MsgSpecRoute` — `APIRoute` subclass that wraps incoming requests with `MSGSpecJSONRequest`. Inherits `APIRoute.__init__` verbatim so it stays forward-compatible with new FastAPI kwargs. |
| `openapi.py`   | `msgspec_response(type)` and `install_msgspec_openapi(app)` — generate JSON schema for `Struct` return types and merge component schemas into the final OpenAPI document. |

## Usage

```python
from fastapi import APIRouter
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import (
    install_msgspec_openapi,
    msgspec_response,
)
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from http_fastapi.fastapi_msgspec.routing import MsgSpecRoute

app = build_app(default_response_class=MsgSpecJSONResponse)
install_msgspec_openapi(app)

router = APIRouter(prefix="/api/v1/projects", route_class=MsgSpecRoute)

@router.get(
    "/",
    response_model=None,                                 # required
    openapi_extra=msgspec_response(list[Project]),       # provides the schema
)
def list_projects() -> MsgSpecJSONResponse:
    return MsgSpecJSONResponse(samples_project)          # return a Response
```

### Rules to follow

1. **`response_model=None`** — `Project` is a `msgspec.Struct`, not a Pydantic
   model. Without this, FastAPI raises
   `Invalid args for response field! ... is a valid Pydantic field type`.
2. **Return a `Response` instance** (e.g. `MsgSpecJSONResponse(...)`) — when
   the handler returns a `Response`, FastAPI skips its `serialize_response`
   path, which would otherwise call `jsonable_encoder()` and fail on
   `Struct` (`vars() argument must have __dict__ attribute`).
3. **Use `msgspec_response(<return type>)`** for OpenAPI schema. Without it,
   the path operation appears in the doc but has no response schema.
4. **Call `install_msgspec_openapi(app)` once.** It overrides `app.openapi`
   so that component schemas registered via `msgspec_response` are merged
   into `components.schemas`.
5. **`MsgSpecRoute` is only needed for request decoding** (POST/PUT JSON
   bodies). For pure GET endpoints, setting `default_response_class` on the
   app is enough.

## Why — performance analysis

### The default FastAPI pipeline (Pydantic)

For each response, FastAPI executes:

1. **Pydantic validation** of the returned object against `response_model`
   (`model_validate`).
2. **Pydantic serialization** to a `dict` (`model_dump`).
3. **`jsonable_encoder`** — pure-Python recursive walk converting `datetime`,
   `UUID`, `Decimal`, enums, nested models, etc. into JSON-safe primitives.
4. **`json.dumps`** from stdlib (C, but generic).

### This integration's pipeline (msgspec)

When the handler returns a `Response` instance, FastAPI **skips
`serialize_response` entirely**. Then:

1. `msgspec.json.encode(value)` — a single C call walking the `Struct`'s
   `__slots__` directly and emitting JSON bytes.

Three layers (Pydantic validate, Pydantic dump, `jsonable_encoder`) are
eliminated; stdlib `json` is replaced by a faster C encoder.

### Order-of-magnitude gains

Based on the msgspec author's published benchmarks:

| Operation | Pydantic v2 | msgspec | Speedup |
|---|---|---|---|
| Encode struct → JSON bytes | 1× | 5–10× | 5–10× |
| Decode JSON → struct       | 1× | 10–20× | 10–20× |
| Validate Python obj        | 1× | 10–50× | 10–50× |
| Memory per instance        | 1× | 0.3–0.5× | 2–3× smaller |

End-to-end FastAPI request, including ASGI/Starlette overhead:

| Payload size | Realistic speedup |
|---|---|
| 1–10 objects        | 1.5–3× |
| 100–1,000 objects   | 3–6× |
| 10k+ nested objects | 5–10× |

### Secondary benefits

- **Lower CPU** under load → more RPS per core, lower cloud cost.
- **Less GC pressure** — `Struct` has no per-instance `__dict__`; encoding
  doesn't allocate intermediate dicts.
- **Lower p99 latency** — less Python-level recursion means fewer GC pauses.
- **Native `datetime` / `UUID` / `Decimal`** encoding in C, instead of the
  `jsonable_encoder` isinstance chain.

### Trade-offs

- **No automatic response validation.** Pydantic would catch a wrong return
  shape; msgspec encodes whatever you give it. If needed, call
  `msgspec.convert(value, list[Project])` before returning — still faster
  than Pydantic.
- **Manual OpenAPI wiring** — every msgspec endpoint must declare
  `openapi_extra=msgspec_response(...)`.
- **Cannot use Pydantic-only features** (`model_validator`, computed fields,
  `Field(...)` schema overrides). msgspec has analogues with different APIs.
- **Error responses are unaffected.** `HTTPException` and validation errors
  still go through `jsonable_encoder`; the speedup applies to 2xx paths.

### How to measure for your endpoint

```bash
uv add --dev oha   # or hey / wrk
oha -n 50000 -c 50 http://localhost:8191/api/v1/projects/
```

Compare requests/sec and p99 latency against an equivalent handler that
returns a Pydantic `response_model`. For small payloads the difference is
modest; bump the list to 1,000+ items to observe the full effect.

## TL;DR

By returning `MsgSpecJSONResponse` directly, this integration bypasses
Pydantic validation, Pydantic dumping, and `jsonable_encoder`, replacing
them with one C-level `msgspec.json.encode` call — typically **3–6× faster
response encoding** with 2–3× smaller per-object memory. The cost is losing
Pydantic's response-time validation and writing OpenAPI schema metadata
manually via `msgspec_response(...)`.
