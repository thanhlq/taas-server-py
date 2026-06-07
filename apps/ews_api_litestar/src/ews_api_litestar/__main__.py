# uv run --prerelease=allow python -m ews_api_litestar
#
# uv run --package ews_api_litestar python -m ews_api_litestar
#
# Litestar variant of the ews_api server. The app itself is assembled in
# ``app.py``; this module is just the entry point that starts uvicorn.
import os

# Top level import: configures environment + settings before anything else.
from .bootstrap import settings

from platform_core.utils.uvicorn import run_uvicorn


def main() -> None:
    ASGI_APP_PACKAGE: str = 'ews_api_litestar.app:app'
    os.environ['APP_MODULE_NAME'] = 'ews_api_litestar'

    from .app import app

    if (
        settings.server.RELOAD
        or settings.server.WORKERS > 1
        or os.getenv('WEB_CONCURRENCY') is not None
    ):
        run_uvicorn(
            ASGI_APP_PACKAGE,
            reload=settings.server.RELOAD,
            workers=settings.server.WORKERS,
        )
    else:
        run_uvicorn(app, reload=settings.server.RELOAD, workers=settings.server.WORKERS)


if __name__ == '__main__':
    main()
