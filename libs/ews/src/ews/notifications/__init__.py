"""Platform notifications (taas-specs/ppm/automation/automation-spec.md Part A, ADR-24): one in-app inbox for every
app, e-mail (instant · digest), preferences per user × kind × channel and delivery settings.

Apps register their kinds (``register_kinds``) and call ``notify`` inside their transaction; the runner
(``NOTIFICATIONS_RUNNER=api|worker|off``) sends e-mails / digests and runs the scheduled jobs apps register
(``register_job``). API: ``/api/v1/notifications``.
"""

from foundation.http import BaseController

from ._delivery import register_job, run_once, start_runner, stop_runner
from ._kinds import Kind, all_kinds, kind_of, register_kinds
from ._service import Recipient, notify, resolve
from .controllers import NotificationController


def get_notification_controllers() -> list[BaseController]:
    return [NotificationController()]


__all__ = [
    'Kind',
    'Recipient',
    'all_kinds',
    'get_notification_controllers',
    'kind_of',
    'notify',
    'register_job',
    'register_kinds',
    'resolve',
    'run_once',
    'start_runner',
    'stop_runner',
]
