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

def main():
    from .app import app

    # One instance per controller, shared by HTTP routes and Socket.IO events
    # so handlers on the same controller can share state.
    controllers = [cls() for cls in ews_conrrollers]

    for controller in controllers:
        include_controller(app, controller)

    # Socket.IO is the default real-time transport: it wraps the FastAPI app so
    # Socket.IO traffic (default path /socket.io) and HTTP share one ASGI app.
    # The raw-WebSocket route registered by include_controller still works too.
    asgi_app = create_socketio_asgi_app(app, *controllers)

    run_uvicorn(asgi_app)


if __name__ == '__main__':
    main()
