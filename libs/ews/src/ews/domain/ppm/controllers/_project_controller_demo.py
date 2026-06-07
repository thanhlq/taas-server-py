# SHOULD INLUCDE IN local dev/test
# Contain all core features for testing purpose only

from typing import TYPE_CHECKING, Any

import msgspec
from ews.domain.ppm.schemas import Project, TaskNotification, TaskNotificationEvent
from ews.domain.ppm.schemas._project import ProjectEntityPy
from platform_core.http import (
    BaseController,
    WebSocketSession,
    cache,
    get,
    socketio_event,
    websocket,
)
from platform_core.http.response.builders import (
    create_error_response,
    create_paginated_response,
    create_success_response,
)
from platform_core.http.response.responses import ErrorResponse, PaginatedResponse
from platform_core.utils.datetime_utils import now_in_utc
from platform_core.utils.validation import ValidationError

if TYPE_CHECKING:
    from platform_core.http._socketio import SocketIOSession


def _project_room(project_id: int) -> str:
    return f'project:{project_id}'


samples_project: list[Project] = [
    Project(id=1, name='Sample Project', created_at=now_in_utc()),
    Project(id=2, name='Another Project', created_at=now_in_utc()),
]

samples_project2: list[ProjectEntityPy] = [
    ProjectEntityPy(id=1, name='Sample Project', created_at=now_in_utc()),
    ProjectEntityPy(id=2, name='Another Project', created_at=now_in_utc()),
]

async def get_sample_projects() -> list[Project]:
    """Demo feed of projects."""
    print("✅ Fetching projects from the database...")  # To show when the cache is hit/missed.
    return samples_project


def _sample_task_notifications(project_id: int) -> list[TaskNotification]:
    """Demo feed of task notifications for a given project."""
    return [
        TaskNotification(
            event=TaskNotificationEvent.TASK_CREATED,
            project_id=project_id,
            task_id=101,
            title='Draft project brief 1',
            occurred_at=now_in_utc(),
        ),
        TaskNotification(
            event=TaskNotificationEvent.TASK_ASSIGNED,
            project_id=project_id,
            task_id=101,
            title='Draft project brief 2',
            assignee='thanhlq@msn.com',
            occurred_at=now_in_utc(),
        ),
        TaskNotification(
            event=TaskNotificationEvent.TASK_ASSIGNED,
            project_id=project_id,
            task_id=101,
            title='Draft project brief 3',
            assignee='thanhlq@msn.com',
            occurred_at=now_in_utc(),
        ),
    ]


class ProjectController(BaseController):
    api_prefix = '/api/v1/test-apis'
    tags = ('Project API TEST',)

    @get('/cached-projects')
    @cache(expire=5)  # Cache this endpoint for 5 seconds
    async def list_projects(self) -> list[Project]:
        return await get_sample_projects()

    @get('/rfc7807')
    @cache(expire=5)  # Cache this endpoint for 5 seconds
    async def list_projects_rfc7807(self) -> PaginatedResponse[Project]:
        projects = await get_sample_projects()
        return create_paginated_response(projects)

    @get(path='/pydantic-serialization')
    def list_projects2(self) -> list[ProjectEntityPy]:
        return samples_project2

    @get(path='/rate-limit-3-per-minutes/{n}', ratelimit='3/minute')
    def list_projects3(self) -> list[ProjectEntityPy]:
        return samples_project2

    @get(path='/{id}')
    def get_projects_by_id(self, id: int) -> Project:
        return create_success_response[Project](samples_project[id])

    @get(path='/error')
    def get_project_error(self) -> Project | ErrorResponse:
        ex = ValidationError(f'Project with id {id} not found')
        return create_error_response( ex, message=str(ex), status=404)


    @websocket('/tasks/notifications', name='project_task_notifications')
    async def task_notifications(self, socket: WebSocketSession) -> None:
        """Stream project task notifications (created, assigned, ...).

        Protocol:
          1. Client connects and receives a ``connected`` control frame.
          2. Client sends ``{"action": "subscribe", "project_id": <int>}``;
             the server replies with the current task notifications for that
             project, then keeps the channel open.
          3. ``{"action": "ping"}`` is answered with a ``pong`` frame.
        """
        await socket.accept()
        await socket.send_json({'type': 'connected', 'channel': 'project-tasks'})

        while True:
            try:
                command = await socket.receive_json()
            except Exception:
                # Client disconnected (or sent a non-JSON / close frame).
                break

            action = (command or {}).get('action')
            if action == 'subscribe':
                project_id = int(command.get('project_id', 0))
                await socket.send_json({'type': 'subscribed', 'project_id': project_id})
                for notification in _sample_task_notifications(project_id):
                    await socket.send_json(msgspec.to_builtins(notification))
            elif action == 'ping':
                await socket.send_json({'type': 'pong'})
            else:
                await socket.send_json({'type': 'error', 'message': 'unknown action'})

    # ---- Socket.IO variant of the same task-notification feed --------------
    # Same business logic over Socket.IO: event-based, with rooms so a task
    # update can fan out to every client subscribed to that project.

    @socketio_event('connect')
    async def sio_connect(self, session: 'SocketIOSession', data: Any) -> None:
        await session.emit_to_caller('connected', {'channel': 'project-tasks'})

    @socketio_event('subscribe')
    async def sio_subscribe(self, session: 'SocketIOSession', data: Any) -> None:
        project_id = int((data or {}).get('project_id', 0))
        await session.enter_room(_project_room(project_id))
        await session.emit_to_caller('subscribed', {'project_id': project_id})
        for notification in _sample_task_notifications(project_id):
            await session.emit_to_caller(
                notification.event.value, msgspec.to_builtins(notification)
            )

    @socketio_event('ping')
    async def sio_ping(self, session: 'SocketIOSession', data: Any) -> None:
        await session.emit_to_caller('pong', {})
