"""OpenAPI integration for msgspec.Struct types in FastAPI.

FastAPI can't introspect ``msgspec.Struct`` into its OpenAPI doc, so we:

* Build a JSON Schema for the return type via :func:`msgspec.json.schema_components`.
* Attach it to a path operation through ``openapi_extra``.
* Merge the discovered components into ``components.schemas`` of the final
  OpenAPI document via :func:`install_msgspec_openapi`.
"""
from __future__ import annotations

from typing import Any

import msgspec
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Private key used to stash component schemas on each route's openapi_extra
# until the global merger picks them up.
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


def msgspec_request_body(
    body_type: Any,
    *,
    required: bool = True,
    description: str | None = None,
) -> dict[str, Any]:
    """Build an ``openapi_extra`` dict describing a msgspec request body."""
    (schema,), components = msgspec.json.schema_components(
        [body_type],
        ref_template="#/components/schemas/{name}",
    )
    body: dict[str, Any] = {
        "required": required,
        "content": {"application/json": {"schema": schema}},
    }
    if description:
        body["description"] = description
    return {
        "requestBody": body,
        _COMPONENTS_KEY: components,
    }


def install_msgspec_openapi(app: FastAPI) -> None:
    """Install a custom ``app.openapi`` that merges msgspec component schemas."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for route in app.routes:
            extra = getattr(route, "openapi_extra", None) or {}
            for name, comp in (extra.get(_COMPONENTS_KEY) or {}).items():
                components.setdefault(name, comp)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
