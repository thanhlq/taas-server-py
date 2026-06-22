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


class cli:
    """Convenience class to access CLI functions. All methods are static and can be called directly without instantiation."""

    @staticmethod
    def info(text: str) -> None:
        console.print(f'[bold cyan]{text}[/]')

    @staticmethod
    def debug(text: str) -> None:
        console.print(f'[dim]{text}[/]')

    @staticmethod
    def error(text: str) -> None:
        console.print(f'[bold red]{text}[/]')

    @staticmethod
    def warning(text: str) -> None:
        console.print(f'[bold yellow]{text}[/]')

    @staticmethod
    def success(text: str) -> None:
        console.print(f'[bold green]{text}[/]')

    @staticmethod
    def info_formal(key: str, value: str) -> None:
        # Print table for formal key-value pairs
        table = Table(show_header=False)
        table.add_column('title', style='cyan')
        table.add_column('value', style='bright_blue')
        table.add_row(key, f'[bold cyan]{value}[/]')
        # table.box = None  # Remove table borders
        console.print(table)

    @staticmethod
    def success_formal(key: str, value: str) -> None:
        # Print table for formal key-value pairs
        table = Table(show_header=False)
        table.add_column('title', style='green')
        table.add_column('value', style='bright_green')
        table.add_row(key, f'[bold green]{value}[/]')
        # table.box = None  # Remove table borders
        console.print(table)

    @staticmethod
    def error_formal(key: str, value: str) -> None:
        # Print table for formal key-value pairs
        table = Table(show_header=False)
        table.add_column('title', style='red')
        table.add_column('value', style='bright_red')
        table.add_row(key, f'[bold red]{value}[/]')
        # table.box = None  # Remove table borders
        console.print(table)

    @staticmethod
    def warning_formal(key: str, value: str) -> None:
        # Print table for formal key-value pairs
        table = Table(show_header=False)
        table.add_column('title', style='yellow')
        table.add_column('value', style='bright_yellow')
        table.add_row(key, f'[bold yellow]{value}[/]')
        # table.box = None  # Remove table borders
        console.print(table)

    @staticmethod
    def debug_formal(key: str, value: str) -> None:
        # Print table for formal key-value pairs
        table = Table(show_header=False)
        table.add_column('title', style='dim')
        table.add_column('value', style='bright_black')
        table.add_row(key, f'[dim]{value}[/]')
        # table.box = None  # Remove table borders
        console.print(table)
