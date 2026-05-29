import os

from typing import Any, TYPE_CHECKING

from platform_core.utils.version import get_version
from rich import get_console
from rich.table import Table

if TYPE_CHECKING:
    from platform_core.http.base_app import BaseApiApplication

console = get_console()

__version__ = get_version()

console = get_console()


def _format_is_enabled(value: Any) -> str:
    """Return a coloured string `"Enabled" if ``value`` is truthy, else "Disabled"."""
    return '[green]Enabled[/]' if value else '[red]Disabled[/]'


def show_all_environment_variables() -> None:
    """
    Print all environment variables from the os.environ to the console.
    Replace passwords or secrets with '[red]REDACTED[/]'.
    """
    console.print('[bold underline]Environment Variables[/]')
    table = Table(show_header=True, header_style='bold magenta')
    table.add_column('Variable', style='dim', width=40)
    table.add_column('Value')

    for key, value in sorted(os.environ.items()):
        display_value = value
        if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'key']):
            display_value = '[red]REDACTED[/]'
        table.add_row(key, display_value)

    console.print(table)


def show_api_app_info(app: 'BaseApiApplication') -> None:  # pragma: no cover
    """Display basic information about the application and its configuration."""

    table = Table(show_header=False)
    table.add_column('title', style='cyan')
    table.add_column('value', style='bright_blue')

    table.add_row(
        'App id',
        f'{app.get_app_id()}, type={type(app.get_app()).__name__}',
    )
    table.add_row(
        'App version',
        f'{__version__.major}.{__version__.minor}.{__version__.patch}',
    )
    table.add_row('Debug mode', _format_is_enabled(app.config.debug))
    if app.config.debug:
        table.add_row('DB URL:', app.all_settings.db.URL or 'Not set')
    table.add_row('Root path', app._root_path)
    table.add_row(
        'Python Debugger on exception', _format_is_enabled(app.config.pdb_on_exception)
    )
    # db migration enabled?
    table.add_row(
        'DB MIGRATION',
        f'{_format_is_enabled(app.all_settings.db.MIGRATION_ENABLED)} -> {app.all_settings.db.MIGRATION_PATH}',
    )
    table.add_row(
        'CORS',
        f'{_format_is_enabled(app.config.cors_config)}, allow_origins={app.config.cors_config.allow_origins if app.config.cors_config else "None"}',
    )
    table.add_row('CSRF', _format_is_enabled(app.config.csrf_config))
    if app.config.allowed_hosts:
        allowed_hosts = app.config.allowed_hosts

        table.add_row('Allowed hosts', ', '.join(allowed_hosts))

    ratelimit_enabled = (
        app.config.ratelimit_config and app.config.ratelimit_config.enabled
    )
    table.add_row('Rate Limiting', _format_is_enabled(ratelimit_enabled))
    if ratelimit_enabled:
        table.add_row(
            'Rate limit redis host',
            f'{app.config.ratelimit_config.redis_host if app.config.ratelimit_config else "N/A"}',
        )

    openapi_enabled = _format_is_enabled(app.config.openapi_config)
    table.add_row('OpenAPI', openapi_enabled)

    table.add_row(
        'Compression',
        app.config.compression_config.backend
        if app.config.compression_config
        else '[red]Disabled',
    )

    table.add_row(
        'WebSocket redis host',
        app.config.websocket_config.redis_host
        if app.config.websocket_config
        else '[red]Disabled',
    )

    if app.template_engine:
        table.add_row('Template engine', type(app.template_engine).__name__)

    console.print(table)
