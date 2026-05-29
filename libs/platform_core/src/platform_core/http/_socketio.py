"""Framework-neutral Socket.IO integration.

Socket.IO's ``AsyncServer`` is already independent of the web framework — the
same server is mounted onto FastAPI or Litestar by the per-framework adapters
in ``http_fastapi``/``http_litestar``. This module therefore owns the neutral
pieces: a session wrapper handed to handlers, the server factory, and
controller registration. The framework adapters only mount the resulting ASGI
app.

Business handlers never import ``socketio`` directly; they accept a
:class:`SocketIOSession` and rely on the ``@socketio_event`` decorator.
"""
from __future__ import annotations
from platform_core.cli import cli_print_info, cli_print_debug
from logging import Logger

from typing import Any

import socketio

from platform_core.http.controller import BaseController


class SocketIOSession:
    """Framework-neutral wrapper over a ``socketio.AsyncServer`` + ``sid``.

    Passed to every ``@socketio_event`` handler so business code can emit and
    manage rooms without importing ``socketio`` or any web framework.
    """

    def __init__(
        self,
        server: socketio.AsyncServer,
        sid: str,
        namespace: str = '/',
    ) -> None:
        self._server = server
        self.sid = sid
        self.namespace = namespace

    @property
    def server(self) -> socketio.AsyncServer:
        """The underlying server, for advanced/framework-specific needs."""
        return self._server

    async def emit(
        self,
        event: str,
        data: Any = None,
        *,
        to: str | None = None,
        room: str | None = None,
        skip_sid: str | None = None,
    ) -> None:
        """Emit ``event``. Defaults to broadcasting on this namespace; pass
        ``to``/``room`` to target a specific client or room."""
        await self._server.emit(
            event,
            data,
            to=to,
            room=room,
            skip_sid=skip_sid,
            namespace=self.namespace,
        )

    async def emit_to_caller(self, event: str, data: Any = None) -> None:
        """Emit ``event`` back to the client that triggered this handler."""
        await self._server.emit(
            event, data, to=self.sid, namespace=self.namespace
        )

    async def enter_room(self, room: str) -> None:
        await self._server.enter_room(self.sid, room, namespace=self.namespace)

    async def leave_room(self, room: str) -> None:
        await self._server.leave_room(self.sid, room, namespace=self.namespace)

    async def close(self) -> None:
        await self._server.disconnect(self.sid, namespace=self.namespace)


def build_socketio_server(client_manager=None, logger: Logger | bool = False, **kwargs: Any) -> socketio.AsyncServer:
    """Create an ``AsyncServer`` with sensible defaults for ASGI hosting.

    ``cors_allowed_origins='*'`` is the default so browser Socket.IO clients
    can connect during development; override via ``kwargs`` for production.
    """

    kwargs.setdefault('async_mode', 'asgi')
    # TODO: to check why '*'
    kwargs.setdefault('cors_allowed_origins', '*')
    cli_print_debug(f"Building Socket.IO server with, client_manager: {type(client_manager).__name__}, kwargs: {kwargs}")
    if client_manager is not None:
        kwargs['client_manager'] = client_manager
    if logger:
        kwargs['logger'] = logger
        kwargs['engineio_logger'] = logger
    return socketio.AsyncServer(**kwargs)


async def verify_socketio_manager(
    server: socketio.AsyncServer,
    *,
    expect_redis: bool = False,
    roundtrip: bool = True,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Validate that ``server`` has the manager you think it has.

    Returns a dict describing what's attached so the caller can log it.
    Raises ``RuntimeError`` when ``expect_redis`` is set and the manager is
    not an ``AsyncRedisManager`` (or the Redis round-trip fails).

    ``roundtrip=True`` publishes a probe message and waits to receive it back
    on its own subscription — the only end-to-end proof that pub/sub works.
    Set ``roundtrip=False`` for fast boot when only a type check is needed.
    """
    import asyncio

    manager = server.manager
    info: dict[str, Any] = {
        'manager_class': type(manager).__name__,
        'manager_module': type(manager).__module__,
        'host_id': getattr(manager, 'host_id', None),
    }

    is_redis = isinstance(manager, socketio.AsyncRedisManager)
    info['is_redis'] = is_redis

    if expect_redis and not is_redis:
        raise RuntimeError(
            f'Expected AsyncRedisManager, got {info["manager_class"]}. '
            'Check that client_manager= reaches AsyncServer(**kwargs).'
        )

    if not is_redis:
        cli_print_info(f'Socket.IO manager: {info}')
        return info

    channel = getattr(manager, 'channel', 'socketio')
    info['channel'] = channel
    info['redis_url'] = getattr(manager, 'redis_url', None)

    # AsyncRedisManager populates self.redis lazily — call the same connect
    # method the manager itself uses on first publish so we test the real path.
    if getattr(manager, 'redis', None) is None:
        try:
            manager._redis_connect()
        except Exception as exc:
            raise RuntimeError(
                f'AsyncRedisManager could not connect to {info["redis_url"]!r}: {exc!r}'
            ) from exc

    redis_client = manager.redis
    if redis_client is None:
        raise RuntimeError(
            f'AsyncRedisManager has no .redis client attached after _redis_connect() '
            f'(url={info["redis_url"]!r})'
        )
    info['connected'] = bool(getattr(manager, 'connected', False))

    try:
        pong = await asyncio.wait_for(redis_client.ping(), timeout=timeout)
        info['ping'] = bool(pong)
    except Exception as exc:
        raise RuntimeError(f'Redis PING failed: {exc!r}') from exc

    if roundtrip:
        probe = f'socketio-verify-{id(server)}'
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(channel)
            await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout),
                timeout=timeout,
            )
            await redis_client.publish(channel, probe)

            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            received = False
            while loop.time() < deadline:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=timeout
                )
                if msg and msg.get('type') == 'message':
                    payload = msg.get('data')
                    if isinstance(payload, bytes):
                        payload = payload.decode('utf-8', errors='replace')
                    if payload == probe:
                        received = True
                        break
            info['roundtrip'] = received
            if not received:
                raise RuntimeError(
                    f'Redis pub/sub round-trip failed on channel {channel!r} '
                    f'within {timeout}s — manager is attached but messages are not flowing.'
                )
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass

    cli_print_info(f'Socket.IO manager verified: {info}')
    return info


def _make_dispatch(server: socketio.AsyncServer, handler_meta: Any):
    handler = handler_meta.handler
    event = handler_meta.event
    namespace = handler_meta.namespace

    async def dispatch(sid: str, *args: Any) -> Any:
        session = SocketIOSession(server, sid, namespace)
        # ``connect`` is called as (sid, environ, auth); custom events as
        # (sid, data). Hand the business handler the most useful payload.
        if event == 'connect':
            data = args[1] if len(args) >= 2 else None
        else:
            data = args[0] if args else None
        return await handler(session, data)

    return dispatch


def register_controller(
    server: socketio.AsyncServer,
    controller: BaseController,
) -> socketio.AsyncServer:
    """Register all of ``controller``'s Socket.IO handlers on ``server``."""
    for handler_meta in controller.get_socketio_handlers():
        server.on(
            handler_meta.event,
            _make_dispatch(server, handler_meta),
            namespace=handler_meta.namespace,
        )
    return server


def build_server_for_controllers(
    *controllers: BaseController,
    **server_kwargs: Any,
) -> socketio.AsyncServer:
    """Build a server and register one or more controllers on it."""
    server = build_socketio_server(**server_kwargs)
    for controller in controllers:
        register_controller(server, controller)
    return server
