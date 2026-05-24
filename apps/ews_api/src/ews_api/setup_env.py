from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from platform_core.config import Settings


def setup_environment() -> Settings:
    """Configure the environment variables and path."""
    current_path = Path(__file__).parent.parent.resolve()
    sys.path.append(str(current_path))
    from platform_core.config import get_settings
    # from platform_core.cli._utils import LitestarExtensionGroup

    settings = get_settings()

    os.environ.setdefault('LITESTAR_APP', 'app.server.asgi:create_app')
    os.environ.setdefault('LITESTAR_APP_NAME', settings.app.NAME)
    # os.environ.setdefault("LITESTAR_GRANIAN_IN_SUBPROCESS", "false")
    os.environ.setdefault('LITESTAR_GRANIAN_USE_LITESTAR_LOGGER', 'true')
    # original_format_help = LitestarExtensionGroup.format_help

    print('Starting with db url: ', settings.db.URL)  # noqa: T201

    return settings
