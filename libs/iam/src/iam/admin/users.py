# SHOULD INLUCDE IN local dev/test

from typing import TYPE_CHECKING, Any

import msgspec
from ews.domain.ppm.schemas import Project, TaskNotification, TaskNotificationEvent
from ews.domain.ppm.schemas._project import ProjectEntityPy
from platform_core.http import (
    BaseController,
    WebSocketSession,
    get,
    socketio_event,
    websocket,
)
from platform_core.utils.datetime_utils import now_in_utc

if TYPE_CHECKING:
    from platform_core.http._socketio import SocketIOSession
    
class ProjectController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Project API',)

    @get('/', ratelimit='3/minute')
    def list_projects(self) -> list[Project]:
        return samples_project