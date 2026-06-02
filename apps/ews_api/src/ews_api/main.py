# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

import os

from http_fastapi.uvicorn import run_uvicorn

from .setup_env import settings


def main():
    ASGI_APP_PACKAGE: str = 'ews_api.app:app'
    os.environ['APP_MODULE_NAME'] = 'ews_api'

    from .app import app

    if settings.server.RELOAD or settings.server.WORKERS > 1:
        run_uvicorn(ASGI_APP_PACKAGE, reload=settings.server.RELOAD, workers=settings.server.WORKERS)

    else:
        run_uvicorn(app, reload=settings.server.RELOAD, workers=settings.server.WORKERS)


if __name__ == '__main__':
    main()
