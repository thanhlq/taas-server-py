# uv run --prerelease=allow python -m ews_api.main_litestar
#
# Litestar variant of the ews_api server. The route definitions live in
# ``ews`` and are framework-agnostic; this entry point wires them into a
# Litestar app via ``http_litestar.adapters``.
from litestar import Litestar

from ews.domain.project import ProjectController
from http_litestar.adapters import (
    build_router_for_controller,
    create_socketio_asgi_app,
)
from http_litestar.base_litestar_app import build_app
from http_litestar.uvicorn import run_uvicorn

from .setup_env import setup_environment

settings = setup_environment()

_controller = ProjectController()

app: Litestar = build_app(
    route_handlers=[build_router_for_controller(_controller)],
)

# Socket.IO is the default real-time transport: it wraps the Litestar app so
# Socket.IO traffic (default path /socket.io) and HTTP share one ASGI app.
# The raw-WebSocket route built into the router still works too.
asgi_app = create_socketio_asgi_app(app, _controller)


def main() -> None:
    print('Hello from ews-api (litestar)!')
    run_uvicorn(asgi_app)


if __name__ == '__main__':
    main()
