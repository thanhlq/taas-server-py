from foundation.http import BaseController

from .controllers._project_api import ProjectController, TaskController
from .controllers._task_activity_api import TaskCommentController, TaskTimelogController
from .controllers._task_planning_api import (
    ProjectIterationController,
    ProjectTaskListController,
)
from .controllers._test_controller_demo import TestController
from .repos import RepoFactory


def get_project_controllers() -> list[BaseController]:
    """
    Get the list of project controllers.
    """
    project_controllers: list[BaseController] = [
        ProjectController(),
        TaskController(),
        ProjectTaskListController(),
        ProjectIterationController(),
        TaskCommentController(),
        TaskTimelogController(),
        TestController(),
    ]
    return project_controllers


__all__ = [
    'get_project_controllers',
    'RepoFactory',
]
