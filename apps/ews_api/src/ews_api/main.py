# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

from ews.domain.project import ProjectController
from rest_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from rest_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from rest_fastapi.fastapi_msgspec.routing import MsgSpecRoute
from fastapi import APIRouter
from rest_fastapi.base_fastapi_app import build_app
from rest_fastapi.uvicorn import run_uvicorn

from .setup_env import setup_environment

settings = setup_environment()

app = build_app(default_response_class=MsgSpecJSONResponse)
install_msgspec_openapi(app)


def main():
    print('Hello from ews-api!')

    router = APIRouter(
        prefix=ProjectController.api_prefix,
        tags=['Project API'],
        route_class=MsgSpecRoute,
    )

    ProjectController(router)

    app.include_router(router)

    run_uvicorn(app)


if __name__ == '__main__':
    main()
