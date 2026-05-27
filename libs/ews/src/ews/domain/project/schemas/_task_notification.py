from datetime import datetime
from enum import Enum
from typing import Optional

from platform_core.serialization import ApiResponse


class TaskNotificationEvent(str, Enum):
    """Kinds of project task notifications pushed over the WebSocket."""

    TASK_CREATED = 'task.created'
    TASK_ASSIGNED = 'task.assigned'
    TASK_UPDATED = 'task.updated'
    TASK_COMPLETED = 'task.completed'


class TaskNotification(ApiResponse):
    """A single project-task notification streamed to subscribed clients."""

    event: TaskNotificationEvent
    project_id: int
    task_id: int
    title: str
    assignee: Optional[str] = None
    occurred_at: Optional[datetime] = None
