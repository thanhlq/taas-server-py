from rich.table import Table
from rich import get_console



console = get_console()


def cli_print_info(text: str) -> None:
    console.print(f'[bold cyan]{text}[/]')

def cli_print_debug(text: str) -> None:
    console.print(f'[dim]{text}[/]')

def cli_print_error(text: str) -> None:
    console.print(f'[bold red]{text}[/]')

def cli_print_warning(text: str) -> None:
    console.print(f'[bold yellow]{text}[/]')

def cli_print_success(text: str) -> None:
    console.print(f'[bold green]{text}[/]')

def cli_print_info_formal(key: str, value: str) -> None:
    # Print table for formal key-value pairs
    table = Table(show_header=False)
    table.add_column('title', style='cyan')
    table.add_column('value', style='bright_blue')
    table.add_row(key, f'[bold cyan]{value}[/]')
    # table.box = None  # Remove table borders
    console.print(table)
