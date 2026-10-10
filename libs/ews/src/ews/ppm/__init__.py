from foundation.config import get_settings
from foundation.http import BaseController

from .controllers._bulk_api import ProjectBulkController, TaskExportController
from .controllers._checklist_api import TaskChecklistController
from .controllers._files_api import ProjectFilesController, TaskFilesController
from .controllers._my_work_api import MyWorkController
from .controllers._overview_api import PpmOverviewController, ProjectMetricsController
from .controllers._automation_api import PpmAutomationController
from .controllers._intake_api import PpmFormController, PpmPublicIntakeController, PpmRequestController
from .controllers._project_contacts_api import PpmContactProjectsController
from .controllers._dashboards_api import (
    PpmDashboardController,
    PpmReportController,
    PpmWidgetController,
    ProjectSeriesController,
)
from .controllers._health_api import PpmHealthPolicyController, ProjectHealthController
from .controllers._members_api import PpmRolesController, ProjectMembersController
from .controllers._project_api import ProjectController
from .controllers._schedule_api import (
    ProjectScheduleController,
    TaskDependencyController,
)
from .controllers._settings_api import PpmSettingsController
from .controllers._time_api import (
    PpmTimeController,
    PpmTimesheetController,
    ProjectTimeController,
    TaskEffortController,
)
from .controllers._task_api import TaskController
from .controllers._task_activity_api import (
    ProjectCommentController,
    TaskCommentController,
    TaskTimelogController,
)
from .controllers._work_model_api import (
    PpmApprovalController,
    PpmApprovalPolicyController,
    PpmChecklistTemplateController,
    PpmCustomFieldController,
    PpmItemTypeController,
    PpmProjectTemplateController,
    ProjectFieldsController,
    ProjectTemplateActionsController,
    TaskChecklistTemplateController,
)
from .controllers._workflow_api import (
    PpmTeamController,
    ProjectWorkflowController,
    WorkflowStageTypeController,
    WorkflowTemplateController,
)
from .controllers._task_planning_api import (
    ProjectIterationController,
    ProjectTaskListController,
)
from .controllers._test_controller_demo import TestController
from . import _notify  # noqa: F401 — registers the notification kinds, rules and reminder job
from . import _custom_fields  # noqa: F401 — registers the required-fields completion guard
from . import _approvals  # noqa: F401 — registers the task approval subject and its completion guard
from . import _recurrence  # noqa: F401 — creates the next occurrence of recurring items
from . import _schedule  # noqa: F401 — keeps the schedule of auto items current (Ppm-1060)
from . import _time  # noqa: F401 — effort, timesheet approvals, variance alerts, timer auto-stop
from . import _health  # noqa: F401 — health refresh job + override notices
from . import _stats  # noqa: F401 — daily statistics job (trends, burnup / burndown)
from . import _automation  # noqa: F401 — automation rules: event subscriber + tick job
from .repos import RepoFactory


def get_project_controllers() -> list[BaseController]:
    """
    Get the list of project controllers.
    """
    project_controllers: list[BaseController] = [
        # static paths (``/bulk``, ``/export.csv``) before ``/{project_id}`` / ``/{task_id}``
        ProjectBulkController(),
        TaskExportController(),
        ProjectController(),
        ProjectMembersController(),
        PpmRolesController(),
        PpmSettingsController(),
        PpmTeamController(),
        PpmTimeController(),
        PpmTimesheetController(),
        PpmHealthPolicyController(),
        PpmWidgetController(),
        PpmDashboardController(),
        PpmReportController(),
        PpmAutomationController(),
        PpmFormController(),
        PpmRequestController(),
        PpmPublicIntakeController(),
        PpmContactProjectsController(),
        PpmItemTypeController(),
        PpmCustomFieldController(),
        PpmChecklistTemplateController(),
        PpmApprovalPolicyController(),
        PpmApprovalController(),
        PpmProjectTemplateController(),
        ProjectFieldsController(),
        ProjectTemplateActionsController(),
        ProjectScheduleController(),
        ProjectTimeController(),
        ProjectHealthController(),
        ProjectSeriesController(),
        MyWorkController(),
        PpmOverviewController(),
        ProjectMetricsController(),
        TaskController(),
        TaskChecklistController(),
        TaskChecklistTemplateController(),
        TaskDependencyController(),
        TaskEffortController(),
        ProjectFilesController(),
        TaskFilesController(),
        ProjectTaskListController(),
        ProjectIterationController(),
        TaskCommentController(),
        ProjectCommentController(),
        TaskTimelogController(),
        WorkflowTemplateController(),
        WorkflowStageTypeController(),
        ProjectWorkflowController(),
    ]
    # Demo routes (`/api/v1/test-apis`): local / test / development only, never staging or production.
    if get_settings().environment in ('local', 'test', 'development'):
        project_controllers.append(TestController())
    return project_controllers


__all__ = [
    'get_project_controllers',
    'RepoFactory',
]
