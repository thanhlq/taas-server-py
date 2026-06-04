import logging
from collections.abc import Callable
from typing import Any, Optional

import uvicorn

# Map Python logging levels to Uvicorn log level strings
UVICORN_LOG_LEVEL_MAP = {
    logging.CRITICAL: 'critical',  # 50
    logging.ERROR: 'error',  # 40
    logging.WARNING: 'warning',  # 30
    logging.INFO: 'info',  # 20
    logging.DEBUG: 'debug',  # 10
    logging.NOTSET: 'info',  # 0 - default to info
}


def run_uvicorn(
    app: Callable[..., Any] | str,
    *,
    port: int = 8191,
    host: str = "0.0.0.0",
    log_config: Optional[dict] = None,
    log_level: Optional[str] = None,
    reload: bool = False,
    workers: int = 1,
):
    """
    Args:
        - host:
            local development: 127.0.0.1
            docker containers: 0.0.0.0
            Production (Behind Proxy): 127.0.0.1
            kubernetes: 0.0.0.0
        - port: The port number to bind the Uvicorn server to.
    """

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_config=log_config,
        log_level=log_level,
        # workers=workers,
        access_log=False,  # Disable Uvicorn's default access log to reduce noise; use custom logging in the app instead
        # loop='auto',
    )
