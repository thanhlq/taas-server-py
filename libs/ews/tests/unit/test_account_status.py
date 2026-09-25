"""The CRM account status catalog: a colour per status, legacy values mapped."""

from db.models.ews.ews_enums import CrmAccountStatus
from ews._status_color import StatusColor
from ews.crm._account_status import ACCOUNT_STATUS_COLORS, account_status, account_status_color


def test_every_status_has_a_colour():
    assert set(ACCOUNT_STATUS_COLORS) == set(CrmAccountStatus)


def test_colours():
    assert account_status_color('Active Customer') is StatusColor.GREEN
    assert account_status_color('Prospect') is StatusColor.BLUE
    assert account_status_color('Churned') is StatusColor.RED
    assert account_status_color('Target') is StatusColor.PURPLE


def test_legacy_lowercase_values_map_to_the_catalog():
    assert account_status('active') is CrmAccountStatus.ACTIVE_CUSTOMER
    assert account_status('prospect') is CrmAccountStatus.PROSPECT
    assert account_status_color('inactive') is StatusColor.GRAY


def test_unknown_is_gray():
    assert account_status('whatever') is None
    assert account_status_color(None) is StatusColor.GRAY
