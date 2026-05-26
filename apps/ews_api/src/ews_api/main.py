# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

from fastapi import FastAPI

from ews.domain.project import ProjectController
from http_fastapi.adapters import include_controller
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from http_fastapi.uvicorn import run_uvicorn

from .setup_env import setup_environment

settings = setup_environment()

app: FastAPI = build_app(default_response_class=MsgSpecJSONResponse)
install_msgspec_openapi(app)


def main():
    print('Hello from ews-api!')

    include_controller(app, ProjectController())

    app.add_api_route('/hello', lambda: {'message': 'Hello, World!'}, methods=['GET'])

    run_uvicorn(app)


if __name__ == '__main__':
    main()
