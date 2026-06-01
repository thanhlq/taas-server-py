# uv run --prerelease=allow python -m ews_api_litestar.main
#
# Litestar variant of the ews_api server. The route definitions live in
# ``ews`` and are framework-agnostic; this entry point wires them into a
# Litestar app via ``http_litestar.adapters``.
import os

os.environ['APP_MODULE_NAME'] = 'ews_api_litestar'

from contextlib import asynccontextmanager
from typing import Optional

import socketio
from litestar import Litestar

from ews.domain.ppm import ProjectController
from http_litestar.adapters import (
    build_router_for_controller,
    create_socketio_asgi_app,
)
from http_litestar.base_litestar_app import build_app
from http_litestar.uvicorn import run_uvicorn

from platform_core.cli import cli_print_info
from platform_core.config.openapi import build_openapi_config
from platform_core.http import AppConfig
from platform_core.http._socketio import verify_socketio_manager
from platform_core.http._websocket_redis_manager import build_websocket_redis_manager

from .setup_env import settings, root_path


def _build_app_config(settings) -> AppConfig:
    app_config = AppConfig(
        app_name=settings.app.NAME,
        compression_config=settings.app.get_compression_config(),
        ratelimit_config=settings.app.get_ratelimit_config(),
        distributed_lock_config=settings.app.get_distributed_lock_config(),
        websocket_config=settings.app.get_websocket_config(),
        cors_config=settings.app.get_cors_config(),
        debug=settings.app.DEBUG,
    )
    if settings.app.OPENAPI_ENABLED:
        app_config.openapi_config = build_openapi_config(
            title=f'{settings.app.NAME} API',
            version=settings.app.VERSION,
        )
    return app_config


def main() -> None:
    app_config = _build_app_config(settings)

    _controller = ProjectController()

    # ``server`` is populated below before any lifespan hook can run.
    server: Optional[socketio.AsyncServer] = None

    @asynccontextmanager
    async def lifespan(_app: Litestar):
        cli_print_info('Starting up the application...')
        if app_config.websocket_config and app_config.websocket_config.debug:
            cli_print_info('🐛 WebSocket debug mode is enabled.')
            assert server is not None, 'socketio server must be built before lifespan starts'
            await verify_socketio_manager(server, expect_redis=True, roundtrip=True)
        yield
        cli_print_info('Shutting down the application...')

    async def _global_exception_handler(_request, _exc):
        import traceback
        traceback.print_exc()
        from litestar.response import Response
        return Response(
            content={'detail': 'Internal Server Error'},
            status_code=500,
        )

    litestar_app: Litestar = build_app(
        route_handlers=[build_router_for_controller(_controller)],
        lifespan=[lifespan],
        exception_handlers={Exception: _global_exception_handler},
    )

    websocket_config = app_config.websocket_config
    assert websocket_config is not None, 'websocket_config must be set for socketio'
    asgi_app, server = create_socketio_asgi_app(
        litestar_app,
        _controller,
        client_manager=build_websocket_redis_manager(websocket_config),
    )

    run_uvicorn(asgi_app)


if __name__ == '__main__':
    main()
