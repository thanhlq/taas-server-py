from __future__ import annotations

import functools
import inspect
import typing
from typing import Annotated, Any, Callable, get_args

import msgspec
from fastapi import Depends, HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from http_fastapi.fastapi_msgspec.openapi import msgspec_response
from http_fastapi.fastapi_msgspec.requests import MSGSpecJSONRequest
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse


def _contains_struct(tp: Any) -> bool:
    """Return True if *tp* is, or contains, a ``msgspec.Struct`` subclass.

    Walks generic type arguments (``list[Project]``, ``dict[str, Project]``,
    ``Project | None``, etc.) recursively.
    """
    if tp is None or tp is type(None):
        return False
    if isinstance(tp, type) and issubclass(tp, msgspec.Struct):
        return True
    return any(_contains_struct(arg) for arg in get_args(tp))


def _make_struct_body_dependency(struct_type: type) -> Callable[..., Any]:
    """Build a FastAPI dependency that decodes the request body into *struct_type*.

    Lets endpoints declare ``data: SomeStruct`` parameters without FastAPI
    trying to introspect the ``msgspec.Struct`` as a Pydantic body field.
    """

    async def _decode_body(request: Request) -> Any:
        body = await request.body()
        try:
            return msgspec.json.decode(body, type=struct_type)
        except msgspec.ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except msgspec.DecodeError as exc:
            raise HTTPException(status_code=400, detail=f'Invalid JSON: {exc}') from exc

    _decode_body.__name__ = f'_decode_{struct_type.__name__}_body'
    return _decode_body


def _rewrite_struct_params(
    endpoint: Callable[..., Any], type_hints: dict[str, Any]
) -> Callable[..., Any]:
    """Wrap *endpoint* so msgspec.Struct parameters become body dependencies.

    FastAPI cannot build a request model field from a ``msgspec.Struct``. To
    keep ergonomic ``data: MyStruct`` signatures on controller methods, we
    rewrite the wrapper's signature so each such parameter is annotated as
    ``Annotated[MyStruct, Depends(<body decoder>)]``. FastAPI then resolves
    the value via the dependency, and the original handler is called with
    the decoded ``Struct`` instance.

    Non-Struct parameters are left untouched.
    """
    sig = inspect.signature(endpoint)
    new_params: list[inspect.Parameter] = []
    rewrote = False
    for param in sig.parameters.values():
        ann = type_hints.get(param.name, param.annotation)
        if (
            ann is not inspect.Parameter.empty
            and isinstance(ann, type)
            and issubclass(ann, msgspec.Struct)
        ):
            dep = _make_struct_body_dependency(ann)
            new_ann = Annotated[ann, Depends(dep)]
            new_params.append(param.replace(annotation=new_ann))
            rewrote = True
        else:
            new_params.append(param)

    if not rewrote:
        return endpoint

    new_sig = sig.replace(parameters=new_params)

    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await endpoint(*args, **kwargs)

        async_wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(endpoint)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        return endpoint(*args, **kwargs)

    sync_wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    return sync_wrapper


def _wrap_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap *endpoint* so its return value is converted to a ``Response``.

    Returning a ``Response`` instance from the handler short-circuits
    FastAPI's ``serialize_response`` (and therefore ``jsonable_encoder``),
    letting ``msgspec.json.encode`` run on the raw value.
    """
    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Response:
            result = await endpoint(*args, **kwargs)
            if isinstance(result, Response):
                return result
            return MsgSpecJSONResponse(result)

        return async_wrapper

    @functools.wraps(endpoint)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Response:
        result = endpoint(*args, **kwargs)
        if isinstance(result, Response):
            return result
        return MsgSpecJSONResponse(result)

    return sync_wrapper


class MsgSpecRoute(APIRoute):
    """APIRoute that natively supports ``msgspec.Struct`` endpoints.

    When the endpoint's return annotation is (or contains) a
    ``msgspec.Struct`` subclass, this route automatically:

    1. Sets ``response_model=None`` so FastAPI does not try to build a
       Pydantic response field from the annotation.
    2. Injects ``openapi_extra`` populated by
       :func:`msgspec_response` so the path operation has a correct
       JSON-Schema response in the OpenAPI document.
    3. Wraps the endpoint so its returned value is encoded with msgspec
       via :class:`MsgSpecJSONResponse`, bypassing ``jsonable_encoder``.

    Endpoints whose return type is not a ``Struct`` are left untouched and
    behave as standard FastAPI routes (Pydantic, etc.). Request bodies are
    decoded with msgspec for *all* routes via :class:`MSGSpecJSONRequest`.

    ``__init__`` accepts ``**kwargs`` and forwards them to ``APIRoute``,
    so it remains forward-compatible with new FastAPI keyword arguments.
    """

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        # Resolve stringified annotations (e.g. from `from __future__ import
        # annotations`) so msgspec.Struct types are detected on both
        # parameters and return.
        try:
            type_hints = typing.get_type_hints(endpoint)
        except Exception:
            type_hints = {}

        # Rewrite msgspec.Struct request-body parameters into FastAPI
        # dependencies so FastAPI does not try to build a Pydantic field
        # from a Struct type.
        endpoint = _rewrite_struct_params(endpoint, type_hints)

        return_type = inspect.signature(endpoint).return_annotation
        if isinstance(return_type, str):
            return_type = type_hints.get('return', return_type)
        is_msgspec_endpoint = (
            return_type is not inspect.Signature.empty and _contains_struct(return_type)
        )

        if is_msgspec_endpoint:
            kwargs['response_model'] = None

            schema_extra = msgspec_response(return_type)
            user_extra = kwargs.get('openapi_extra') or {}
            # User-supplied keys win, except 'responses' which are merged
            # status-code-by-status-code (user wins per status code).
            merged: dict[str, Any] = {**schema_extra, **user_extra}
            user_responses = user_extra.get('responses')
            if user_responses:
                merged['responses'] = {
                    **schema_extra['responses'],
                    **user_responses,
                }
            kwargs['openapi_extra'] = merged

            endpoint = _wrap_endpoint(endpoint)

        super().__init__(path, endpoint, **kwargs)

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            request = MSGSpecJSONRequest(request.scope, request.receive)
            return await original_route_handler(request)

        return custom_route_handler
