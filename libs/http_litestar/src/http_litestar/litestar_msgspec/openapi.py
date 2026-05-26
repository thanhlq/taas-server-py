"""OpenAPI integration for msgspec.Struct types in Litestar.

Litestar can't introspect ``msgspec.Struct`` into its OpenAPI doc, so we:

* Build a JSON Schema for the return type via :func:`msgspec.json.schema_components`.
* Attach it to a route handler through ``openapi_extra``.
* Merge the discovered components into ``components.schemas`` of the final
  OpenAPI document via :func:`install_msgspec_openapi`.
"""
from __future__ import annotations

from typing import Any

import msgspec
from litestar import Litestar
from litestar.openapi.spec import OpenAPI

_COMPONENTS_KEY = "x-msgspec-components"

def msgspec_response(
    return_type: Any,
    *,
    status_code: int = 200,
    description: str = "Successful Response",
) -> dict[str, Any]:
    """Build an ``openapi_extra`` dict describing a msgspec response."""
    (schema,), components = msgspec.json.schema_components(
        [return_type],
        ref_template="#/components/schemas/{name}",
    )
    return {
        "responses": {
            str(status_code): {
                "description": description,
                "content": {"application/json": {"schema": schema}},
            }
        },
        _COMPONENTS_KEY: components,
    }

def install_msgspec_openapi(app: Litestar) -> None:
    """Install a custom ``app.openapi`` that merges msgspec component schemas."""
    original_openapi_fn = app.openapi
    def custom_openapi(*args, **kwargs) -> OpenAPI:
        schema = original_openapi_fn(*args, **kwargs)
        components = schema.components.schemas
        for route in app.routes:
            extra = getattr(route, "openapi_extra", None) or {}
            for name, comp in (extra.get(_COMPONENTS_KEY) or {}).items():
                components.setdefault(name, comp)
        return schema
    app.openapi = custom_openapi
