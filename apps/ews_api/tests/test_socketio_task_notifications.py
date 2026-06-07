"""End-to-end Socket.IO tests for the project task-notification feed.

The same framework-agnostic ``ProjectController`` is mounted under both
FastAPI and Litestar via each adapter's ``create_socketio_asgi_app`` and
exercised with a real ``socketio.AsyncClient`` over uvicorn.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable

import pytest
import socketio
import uvicorn
from ews.domain.ppm import ProjectController

EXPECTED_EVENTS = {'connected', 'subscribed', 'task.created', 'task.assigned', 'pong'}


def _build_fastapi_asgi():
    from fastapi import FastAPI
    from http_fastapi.adapters import create_socketio_asgi_app, include_controller
    from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse

    app = FastAPI(default_response_class=MsgSpecJSONResponse)
    controller = ProjectController()
    include_controller(app, controller)
    return create_socketio_asgi_app(app, controller)


def _build_litestar_asgi():
    from http_litestar.adapters import (
        build_router_for_controller,
        create_socketio_asgi_app,
    )
    from http_litestar.base_litestar_app import build_app

    controller = ProjectController()
    app = build_app(route_handlers=[build_router_for_controller(controller)])
    return create_socketio_asgi_app(app, controller)


class _ServerThread:
    def __init__(self, asgi_app, port: int) -> None:
        config = uvicorn.Config(
            asgi_app, host='127.0.0.1', port=port, log_level='warning'
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> '_ServerThread':
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError('server did not start in time')
            time.sleep(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


async def _drive_client(port: int) -> list[tuple[str, object]]:
    sio = socketio.AsyncClient()
    received: list[tuple[str, object]] = []

    for event in EXPECTED_EVENTS:
        sio.on(
            event,
            (lambda ev: (lambda data: received.append((ev, data))))(event),
        )

    await sio.connect(f'http://127.0.0.1:{port}')
    await asyncio.sleep(0.4)
    await sio.emit('subscribe', {'project_id': 2})
    await asyncio.sleep(0.4)
    await sio.emit('ping', {})
    await asyncio.sleep(0.4)
    await sio.disconnect()
    return received


@pytest.mark.parametrize(
    ('builder', 'port'),
    [
        pytest.param(_build_fastapi_asgi, 8211, id='fastapi'),
        pytest.param(_build_litestar_asgi, 8212, id='litestar'),
    ],
)
def test_socketio_task_notifications(builder: Callable[[], object], port: int) -> None:
    with _ServerThread(builder(), port):
        received = asyncio.run(_drive_client(port))

    by_event = dict(received)
    assert EXPECTED_EVENTS <= set(by_event), f'missing events: {received}'
    assert by_event['subscribed'] == {'project_id': 2}
    assert by_event['task.created']['event'] == 'task.created'
    assert by_event['task.created']['projectId'] == 2
    assert by_event['task.assigned']['assignee'] == 'thanhlq@msn.com'
