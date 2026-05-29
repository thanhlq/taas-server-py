from typing import Any

from platform_core.utils.version import get_version
from rich import get_console
from rich.table import Table

console = get_console()

def cli_print_info(text: str) -> None:
    console.print(f'[bold cyan]{text}[/]')

def cli_print_debug(text: str) -> None:
    console.print(f'[dim]{text}[/]')

def cli_print_error(text: str) -> None:
    console.print(f'[bold red]{text}[/]')