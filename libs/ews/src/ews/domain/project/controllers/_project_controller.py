from typing import TYPE_CHECKING, Any

import msgspec

from ews.domain.project.schemas import Project, TaskNotification, TaskNotificationEvent
from ews.domain.project.schemas._project import ProjectEntityPy
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
    api_prefix = '/api/v1/projects'
    tags = ('Project API',)

    @get('/', ratelimit='3/minute')
    def list_projects(self) -> list[Project]:
        return samples_project

    @get(path='/p2', ratelimit='2/minute')
    def list_projects2(self) -> list[ProjectEntityPy]:
        return samples_project2

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
