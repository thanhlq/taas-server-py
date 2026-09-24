"""Project status catalog: the colour and group of every ``ProjectStatus``.

The colour is a semantic tone (not a CSS value) so each client maps it to its own
palette — the web renders the status as a badge tinted with this tone.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from db.models.ews.ews_enums import ProjectStatus


class StatusColor(StrEnum):
    """Semantic badge tones shared by all status catalogs."""

    GRAY = 'gray'
    BLUE = 'blue'
    GREEN = 'green'
    YELLOW = 'yellow'
    ORANGE = 'orange'
    RED = 'red'
    PURPLE = 'purple'
    TEAL = 'teal'


class StatusGroup(StrEnum):
    LIFECYCLE = 'lifecycle'
    RISK = 'risk'
    REVIEW = 'review'
    EXECUTION = 'execution'
    SPECIAL = 'special'


_S = ProjectStatus
_C = StatusColor
_G = StatusGroup

# (colour, group) per status — the single place to change how a status looks.
PROJECT_STATUS_CATALOG: dict[ProjectStatus, tuple[StatusColor, StatusGroup]] = {
    _S.NEW: (_C.BLUE, _G.LIFECYCLE),
    _S.ACTIVE: (_C.GREEN, _G.LIFECYCLE),
    _S.DRAFT: (_C.BLUE, _G.LIFECYCLE),
    _S.PLANNED: (_C.PURPLE, _G.LIFECYCLE),
    _S.IN_PROGRESS: (_C.YELLOW, _G.LIFECYCLE),
    _S.ON_HOLD: (_C.ORANGE, _G.LIFECYCLE),
    _S.COMPLETED: (_C.GREEN, _G.LIFECYCLE),
    _S.CANCELLED: (_C.GRAY, _G.LIFECYCLE),
    _S.ARCHIVED: (_C.GRAY, _G.LIFECYCLE),
    _S.AT_RISK: (_C.RED, _G.RISK),
    _S.BLOCKED: (_C.RED, _G.RISK),
    _S.DELAYED: (_C.ORANGE, _G.RISK),
    _S.AHEAD: (_C.TEAL, _G.RISK),
    _S.PENDING_APPROVAL: (_C.YELLOW, _G.REVIEW),
    _S.UNDER_REVIEW: (_C.PURPLE, _G.REVIEW),
    _S.APPROVED: (_C.GREEN, _G.REVIEW),
    _S.REJECTED: (_C.RED, _G.REVIEW),
    _S.TESTING: (_C.TEAL, _G.EXECUTION),
    _S.DEPLOYMENT: (_C.TEAL, _G.EXECUTION),
    _S.MAINTENANCE: (_C.GRAY, _G.EXECUTION),
    _S.CLOSING: (_C.PURPLE, _G.EXECUTION),
    _S.TEMPLATE: (_C.GRAY, _G.SPECIAL),
    _S.INACTIVE: (_C.GRAY, _G.SPECIAL),
}


def project_status_color(status: Optional[str]) -> StatusColor:
    """Colour of a stored status; unknown / legacy values are gray."""
    try:
        return PROJECT_STATUS_CATALOG[ProjectStatus(status)][0]
    except (KeyError, ValueError):
        return StatusColor.GRAY
