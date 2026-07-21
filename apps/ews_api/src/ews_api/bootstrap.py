"""
The very first code that runs when the ews_api server starts.
- Responsible for setting up the environment variables and path.
- Responsible for building the app config and the Litestar or FastAPI app.
- Bootstrapping the logging, tracing, and other cross-cutting concerns.
The
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from foundation.config import CONFIG_PREFIX
from foundation.storage.providers.fs.fs_paths import FSPaths

if TYPE_CHECKING:
    from foundation.config import Settings

settings: Settings
root_path: str


def setup_environment(env_file: str = '.env') -> tuple[Settings, str]:
    """Configure the environment variables and path."""

    # libs/foundation/src/foundation/storage/providers/fs/fs_paths.py

    # apps/ews_api/src/ews_api/bootstrap.py
    # current_path = Path(__file__).parent.parent.parent.parent.parent.resolve()
    root_path = FSPaths.find_app_root()


    from foundation.config import get_settings

    settings = get_settings(env_file=env_file, home_path=root_path)

    os.environ.setdefault(f'{CONFIG_PREFIX}_APP', 'app.server.asgi:create_app')
    os.environ.setdefault(f'{CONFIG_PREFIX}_APP_NAME', settings.app.NAME)
    # os.environ.setdefault(f"{CONFIG_PREFIX}_GRANIAN_IN_SUBPROCESS", "false")
    # original_format_help = LitestarExtensionGroup.format_help

    # Init Logging (triggered by importing the factory, which is used by the app config and the app itself)
    from foundation.observability.factory import LogFactory

    LogFactory().logger.info('Environment setup complete. Starting application...')

    return settings, root_path


settings, root_path = setup_environment(os.getenv('ENV_FILE', '.env'))

__all__ = ['settings', 'root_path']
