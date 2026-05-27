# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

from fastapi.responses import JSONResponse
from typing import Any
from fastapi import FastAPI

from ews.domain.project import ProjectController
from http_fastapi.adapters import create_socketio_asgi_app, include_controller
from http_fastapi.base_fastapi_app import build_app
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from http_fastapi.uvicorn import run_uvicorn

from .setup_env import setup_environment

settings = setup_environment()

app: FastAPI = build_app(default_response_class=MsgSpecJSONResponse)
install_msgspec_openapi(app)

@app.exception_handler(Exception)
async def global_exception_handler(request: Any, exc: Exception):
    # Print full traceback to console
    print("Unhandled exception occurred:")
    import traceback
    traceback.print_exc()

    # Or log it with your logger instead of print
    # logger.error("Unhandled exception", exc_info=exc)

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


def main():
    print('Hello from ews-api!')

    controller = ProjectController()
    include_controller(app, controller)

    app.add_api_route('/hello', lambda: {'message': 'Hello, World!'}, methods=['GET'])

    # Socket.IO is the default real-time transport: it wraps the FastAPI app so
    # Socket.IO traffic (default path /socket.io) and HTTP share one ASGI app.
    # The raw-WebSocket route registered by include_controller still works too.
    asgi_app = create_socketio_asgi_app(app, controller)

    run_uvicorn(asgi_app)


if __name__ == '__main__':
    main()
