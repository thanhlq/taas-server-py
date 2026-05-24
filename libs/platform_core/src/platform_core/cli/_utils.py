from typing import Any

from platform_core.app import TaasApp
from platform_core.utils.version import get_version
from rich import get_console
from rich.table import Table

console = get_console()

__version__ = get_version()

console = get_console()


def _format_is_enabled(value: Any) -> str:
    """Return a coloured string `"Enabled" if ``value`` is truthy, else "Disabled"."""
    return '[green]Enabled[/]' if value else '[red]Disabled[/]'


def show_app_info(app: TaasApp) -> None:  # pragma: no cover
    """Display basic information about the application and its configuration."""

    table = Table(show_header=False)
    table.add_column('title', style='cyan')
    table.add_column('value', style='bright_blue')

    table.add_row(
        'Litestar version',
        f'{__version__.major}.{__version__.minor}.{__version__.patch}',
    )
    table.add_row('Debug mode', _format_is_enabled(app.debug))
    table.add_row(
        'Python Debugger on exception', _format_is_enabled(app.pdb_on_exception)
    )
    table.add_row('CORS', _format_is_enabled(app.cors_config))
    table.add_row('CSRF', _format_is_enabled(app.csrf_config))
    if app.allowed_hosts:
        allowed_hosts = app.allowed_hosts

        table.add_row('Allowed hosts', ', '.join(allowed_hosts.allowed_hosts))

    openapi_enabled = _format_is_enabled(app.openapi_config)
    table.add_row('OpenAPI', openapi_enabled)

    table.add_row(
        'Compression',
        app.compression_config.backend if app.compression_config else '[red]Disabled',
    )

    if app.template_engine:
        table.add_row('Template engine', type(app.template_engine).__name__)

    console.print(table)
