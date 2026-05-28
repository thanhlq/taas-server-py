from __future__ import annotations
from platform_core.cli import get_console

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from platform_core.config import CONFIG_PREFIX

if TYPE_CHECKING:
    from typing import Any

    from platform_core.config import Settings

_settings: Settings | None = None


def setup_environment() -> Settings:
    global _settings
    if _settings is not None:
        return _settings

    """Configure the environment variables and path."""
    current_path = Path(__file__).parent.parent.parent.parent.parent.resolve()
    sys.path.append(str(current_path))
    from platform_core.config import get_settings

    print('Current path: ', current_path)  # noqa: T201

    _settings = get_settings()

    os.environ.setdefault(f'{CONFIG_PREFIX}_APP', 'app.server.asgi:create_app')
    os.environ.setdefault(f'{CONFIG_PREFIX}_APP_NAME', _settings.app.NAME)
    # os.environ.setdefault(f"{CONFIG_PREFIX}_GRANIAN_IN_SUBPROCESS", "false")
    # original_format_help = LitestarExtensionGroup.format_help

    return _settings


__all__ = ['setup_environment']
