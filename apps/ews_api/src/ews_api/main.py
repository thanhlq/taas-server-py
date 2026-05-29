# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

import asyncio
import os

from http_fastapi.uvicorn import run_uvicorn

from .setup_env import settings


async def main():
    ASGI_APP_PACKAGE: str = 'ews_api.app:app'
    os.environ['APP_MODULE_NAME'] = 'ews_api'

    from .app import app

    if settings.server.RELOAD:
        run_uvicorn(ASGI_APP_PACKAGE, reload=True)

    else:
        run_uvicorn(app)


if __name__ == '__main__':
    asyncio.run(main())
