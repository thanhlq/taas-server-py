from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from platform_core.config import CONFIG_PREFIX

if TYPE_CHECKING:
    from platform_core.config import Settings

settings: Settings
root_path: str


def setup_environment() -> tuple[Settings, str]:
    """Configure the environment variables and path."""
    current_path = Path(__file__).parent.parent.parent.parent.parent.resolve()
    sys.path.append(str(current_path))
    from platform_core.config import get_settings

    root_path = current_path.as_posix()
    settings = get_settings(home_path=root_path)

    os.environ.setdefault(f'{CONFIG_PREFIX}_APP', 'app.server.asgi:create_app')
    os.environ.setdefault(f'{CONFIG_PREFIX}_APP_NAME', settings.app.NAME)
    # os.environ.setdefault(f"{CONFIG_PREFIX}_GRANIAN_IN_SUBPROCESS", "false")
    # original_format_help = LitestarExtensionGroup.format_help

    return settings, root_path


settings, root_path = setup_environment()

__all__ = ['settings', 'root_path']
