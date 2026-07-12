"""
The very first code that runs when the ews_worker starts.

Responsible for configuring environment variables / import path and loading the
application :class:`Settings`, then bootstrapping logging. Mirrors
``ews_api.bootstrap`` so the worker and API share the same configuration model.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foundation.config import Settings

settings: Settings
root_path: str


def setup_environment(env_file: str = '.env') -> tuple[Settings, str]:
    """Configure environment variables / import path and load settings."""
    current_path = Path(__file__).parent.parent.parent.parent.parent.resolve()
    sys.path.append(str(current_path))

    from foundation.config import get_settings

    root_path = current_path.as_posix()
    settings = get_settings(env_file=env_file, home_path=root_path)

    # Init logging (triggered by importing the factory).
    from foundation.observability.factory import LogFactory

    LogFactory().logger.info('EWS worker environment setup complete.')

    return settings, root_path


settings, root_path = setup_environment(os.getenv('ENV_FILE', '.env'))

__all__ = ['settings', 'root_path']
