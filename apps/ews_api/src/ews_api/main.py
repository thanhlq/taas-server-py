# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

from ews_api.app import _setup_fastapi_app
import os
from fastapi.responses import JSONResponse
from typing import Any
from fastapi import FastAPI

from ews import ews_conrrollers
from http_fastapi.adapters import create_socketio_asgi_app, include_controller
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from http_fastapi.uvicorn import run_uvicorn

os.environ['APP_MODULE_NAME'] = 'ews_api'

from .setup_env import setup_environment

ASGI_APP_PACKAGE: str = 'ews_api.main:app'


def main():
    from .app import app

    settings, _ = setup_environment()

    if settings.server.RELOAD:
        run_uvicorn(ASGI_APP_PACKAGE, reload=True)

    else:
        run_uvicorn(app)


if __name__ == '__main__':
    main()
