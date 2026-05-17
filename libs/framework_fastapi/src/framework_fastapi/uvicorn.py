from collections.abc import Callable
from typing import Optional, Any
import logging

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
        log_level=log_level
        # loop='auto',
    )
