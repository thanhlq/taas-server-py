"""Semantic badge tones shared by every status catalog (projects, CRM accounts, …).

A tone is not a CSS value: each client maps it to its own palette.
"""

from enum import StrEnum


class StatusColor(StrEnum):
    GRAY = 'gray'
    BLUE = 'blue'
    GREEN = 'green'
    YELLOW = 'yellow'
    ORANGE = 'orange'
    RED = 'red'
    PURPLE = 'purple'
    TEAL = 'teal'
