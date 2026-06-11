import os
from typing import TYPE_CHECKING, Any

from rich import get_console
from rich.table import Table

from platform_core.utils.version import get_version

if TYPE_CHECKING:
    from platform_core.http.base_app import BaseApiApplication

console = get_console()

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
    __version__ = get_version()

    table = Table(show_header=False)
    table.add_column('title', style='cyan')
    table.add_column('value', style='bright_blue')

    table.add_row(
        'App id',
        f'{app.get_app_id()}, type={type(app.get_app()).__name__}, pid={os.getpid()}',
    )
    table.add_row(
        'VERSION',
        f'{__version__.major}.{__version__.minor}.{__version__.patch}',
    )
    table.add_row('Env/Debug', f'{app.all_settings.environment}/{_format_is_enabled(app.config.debug)}')
    if app.config.debug:
        table.add_row('DB URL:', app.all_settings.db.URL or 'Not set')
    table.add_row('Root path', app.root_app_path())
    table.add_row(
        'Python Debugger on exception', _format_is_enabled(app.config.pdb_on_exception)
    )
    # db migration enabled?
    table.add_row(
        'DB MIGRATION',
        f'{_format_is_enabled(app.all_settings.db.MIGRATION_ENABLED)}',
    )
    table.add_row('DB MIGRATION PATH', app.all_settings.db.MIGRATION_PATH)  # Add an empty column for spacing
    # WORKERS
    workers = os.getenv('WEB_CONCURRENCY') or str(app.all_settings.server.WORKERS)
    table.add_row('WORKERS', workers)
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
    table.add_row('RATE LIMIT', f'{_format_is_enabled(ratelimit_enabled)} - {app.config.ratelimit_config.redis_host if app.config.ratelimit_config else "N/A"}')

    openapi_enabled = _format_is_enabled(app.config.openapi_config)
    table.add_row('OpenAPI', openapi_enabled)

    table.add_row(
        'COMPRESSION',
        app.config.compression_config.backend
        if app.config.compression_config
        else '[red]Disabled',
    )

    table.add_row(
        'WEBSOCKET PUBSUB HOST',
        app.config.websocket_config.redis_host
        if app.config.websocket_config
        else '[red]Disabled',
    )

    if app.template_engine:
        table.add_row('Template engine', type(app.template_engine).__name__)

    console.print(table)
