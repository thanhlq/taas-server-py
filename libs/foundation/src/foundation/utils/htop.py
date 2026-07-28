"""
A script to return cpu/ram/... values as linux htop command does, but in a more structured dict.
"""

import os

is_psutil = False
try:
    import psutil

    is_psutil = True
except ImportError:
    print('💾  psutil module not found. Cpu/ram will not be available')

try:
    import setproctitle

    from foundation.config.settings import get_settings

    setproctitle.setproctitle(f'{get_settings().app.SERVICE_NAME}-py')

except ImportError:
    pass


def human_bytes(num: float, suffix: str = 'B') -> str:
    """Format a byte count as a human-readable string (B, KB, MB, GB, ...).

    Uses binary units (1 KB = 1024 B), matching how htop/free report memory.

    >>> human_bytes(0)
    '0.0 B'
    >>> human_bytes(1536)
    '1.5 KB'
    >>> human_bytes(16 * 1024 ** 3)
    '16.0 GB'
    """
    value = float(num)
    for unit in ('', 'K', 'M', 'G', 'T', 'P', 'E', 'Z'):
        if abs(value) < 1024.0:
            return f'{value:.1f} {unit}{suffix}'
        value /= 1024.0
    return f'{value:.1f} Y{suffix}'


def htop() -> dict:
    """Return a dict of cpu/ram/... values as linux htop command does.

    Byte-valued fields are formatted human-readable (e.g. '15.5 GB'); percent
    fields stay numeric.
    """

    if not is_psutil:
        return {
            'cpu/ram': 'psutil module not found. Please install it with "pip install psutil".'
        }

    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()

    # also get ram used by this process
    process = psutil.Process(os.getpid())
    process_ram = process.memory_info().rss
    process_ram_human = human_bytes(process_ram)

    return {
        'cpu': {
            'percent': psutil.cpu_percent(interval=1),
            'count': psutil.cpu_count(),
        },
        'ram_used_by_app': process_ram_human,
        'ram': {
            'total': human_bytes(vm.total),
            'available': human_bytes(vm.available),
            'percent': vm.percent,
            'used': human_bytes(num=vm.used),
            'free': human_bytes(vm.free),
        },
        'swap': {
            'total': human_bytes(sm.total),
            'used': human_bytes(sm.used),
            'free': human_bytes(sm.free),
            'percent': sm.percent,
        },
    }
