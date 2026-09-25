"""CRM account status catalog: the badge colour of every ``CrmAccountStatus``."""

from __future__ import annotations

from typing import Optional

from db.models.ews.ews_enums import CrmAccountStatus

from .._status_color import StatusColor

_S = CrmAccountStatus

ACCOUNT_STATUS_COLORS: dict[CrmAccountStatus, StatusColor] = {
    _S.TARGET: StatusColor.PURPLE,
    _S.PROSPECT: StatusColor.BLUE,
    _S.ACTIVE_CUSTOMER: StatusColor.GREEN,
    _S.CHURNED: StatusColor.RED,
    _S.INACTIVE: StatusColor.GRAY,
}

# Values stored before the catalog existed (lowercase, free-form).
_LEGACY: dict[str, CrmAccountStatus] = {
    'active': _S.ACTIVE_CUSTOMER,
    'prospect': _S.PROSPECT,
    'inactive': _S.INACTIVE,
    'target': _S.TARGET,
    'churned': _S.CHURNED,
}


def account_status(stored: Optional[str]) -> Optional[CrmAccountStatus]:
    """The catalog status of a stored value (legacy lowercase values included)."""
    if not stored:
        return None
    try:
        return CrmAccountStatus(stored)
    except ValueError:
        return _LEGACY.get(stored.strip().lower())


def account_status_color(stored: Optional[str]) -> StatusColor:
    status = account_status(stored)
    return ACCOUNT_STATUS_COLORS[status] if status else StatusColor.GRAY
