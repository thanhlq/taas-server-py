import json
from typing import Any

from foundation.cli import cli
from foundation.config import get_settings

settings = get_settings()


def is_debug_mode() -> bool:
    return settings.app.DEBUG


if settings.app.DEBUG:
    cli.info_formal('⚠️  Debug', ' Debug mode is enabled')
    from ._debug_rich import debug_exception_r as debug_exception
else:
    from ._debug import debug_exception_do_nothing as debug_exception


def print_dict_pretty(d: dict[Any, Any], title: str = 'Dict Contents'):
    # for debugging purposes
    pretty_json_output = json.dumps(d, indent=4, sort_keys=True)
    print(f'--- {title} ---')
    print(pretty_json_output)
    print('------------------')
    pass


__all__ = [
    'debug_exception',
    'print_dict_pretty',
]
