from collections.abc import Callable
from typing import Any, Optional

import uvicorn


def run_uvicorn(
    app: Callable[..., Any] | str,
    *,
    port: int = 8191,
    host: str = "0.0.0.0",
    log_config: Optional[dict] = None,
    log_level: Optional[str] = None,
    reload: bool = False,
) -> None:
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_config=log_config,
        log_level=log_level,
    )
