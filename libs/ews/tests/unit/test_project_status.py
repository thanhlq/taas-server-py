"""The project status catalog covers every ``ProjectStatus`` with a known colour."""

from db.models.ews.ews_enums import ProjectStatus
from ews.ppm._project_status import (
    PROJECT_STATUS_CATALOG,
    StatusColor,
    project_status_color,
)


def test_every_status_has_a_colour_and_group():
    assert set(PROJECT_STATUS_CATALOG) == set(ProjectStatus)


def test_status_colours():
    assert project_status_color('Active') is StatusColor.GREEN
    assert project_status_color('In Progress') is StatusColor.YELLOW
    assert project_status_color('At Risk') is StatusColor.RED
    assert project_status_color('Draft') is StatusColor.BLUE
    assert project_status_color('Archived') is StatusColor.GRAY


def test_unknown_or_missing_status_is_gray():
    assert project_status_color('Legacy value') is StatusColor.GRAY
    assert project_status_color(None) is StatusColor.GRAY
