import traceback

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.traceback import Traceback

console = Console()


def debug_exception_r(exception: Exception, message: str = ''):
    """Print beautifully formatted exception using Rich"""
    """ TODO: to disable in production """

    # Create traceback object
    tb = Traceback.from_exception(
        type(exception),
        exception,
        exception.__traceback__,
        show_locals=True,  # Show local variables
        max_frames=10,  # Limit frames shown
    )

    # Create a panel with the exception info
    if message:
        title = f'🚨 Exception: {message}'
    else:
        title = f'🚨 {type(exception).__name__}'

    panel = Panel(tb, title=title, border_style='red', expand=False)

    console.print(panel)


def print_rich_error(error_msg: str, details: str = ''):
    """Print error message in a nice format"""

    error_text = Text(error_msg, style='bold red')

    if details:
        content = f'{error_text}\n\nDetails: {details}'
    else:
        content = error_text

    console.print(Panel(content, title='❌ Error', border_style='red'))
