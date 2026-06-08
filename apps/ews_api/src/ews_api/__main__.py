# uv run --prerelease=allow python -m ews_api.main
#
# uv run --package ews_api python main.py

import os

# Top level import
from .bootstrap import settings

from platform_core.utils.uvicorn import run_uvicorn


def main():
    ASGI_APP_PACKAGE: str = 'ews_api.app:app'
    os.environ['APP_MODULE_NAME'] = 'ews_api'

    if (
        settings.server.RELOAD
        or settings.server.WORKERS > 1
        or os.getenv('WEB_CONCURRENCY') is not None
    ):
        # Multiprocess mode (reload/workers): pass the import string so uvicorn
        # builds the app inside the worker subprocess only. Importing the app
        # here in the parent process would build it an extra time.
        run_uvicorn(
            ASGI_APP_PACKAGE,
            reload=settings.server.RELOAD,
            workers=settings.server.WORKERS,
        )

    else:
        # Single-process mode: build/import the app object and run it directly.
        from .app import app

        run_uvicorn(app, reload=settings.server.RELOAD, workers=settings.server.WORKERS)


if __name__ == '__main__':
    main()
