# WebSockets in `platform_core.http`

Reference notes on how WebSocket support works in this codebase, and the
decision between **raw Starlette/Litestar WebSockets** (what we use today) and
**python-socketio**.

## How WebSockets fit the abstraction

WebSocket routes are declared the same framework-agnostic way as HTTP routes:

- `@websocket(path, name=..., **extra)` decorator in
  `platform_core.http.decorator` attaches a `WebSocketRoute` to the handler.
- `BaseController.get_websocket_routes()` collects them (MRO walk, handlers
  bound to the instance), alongside `get_routes()` for HTTP.
- Handlers receive a `WebSocketSession` (`platform_core.http._websocket`) — a
  runtime-checkable Protocol with the intersection of both frameworks' socket
  APIs: `accept / receive_text / receive_json / send_text / send_json / close`.
- Adapters wrap the native socket and register the route:
  - FastAPI: `FastAPIWebSocketSession` + `add_api_websocket_route`
    (`http_fastapi/adapters/_websocket.py`, `_controller.py`)
  - Litestar: `LitestarWebSocketSession` + `WebsocketRouteHandler`
    (`http_litestar/adapters/_websocket.py`, `_controller.py`)

Business libraries (e.g. `ews`) never import FastAPI or Litestar — they depend
only on `platform_core.http`.

### Gotcha: do not use `functools.wraps` on the endpoint wrapper

Both frameworks build their endpoint signature via `inspect.signature`, which
follows `__wrapped__` (set by `functools.wraps`). If wrapped, they look through
to the business handler's `WebSocketSession` annotation and fail to build the
endpoint. The adapters define a plain wrapper exposing the native
`WebSocket`/`socket` parameter directly instead.

### Example

`ews.domain.project.controllers._project_controller.ProjectController` exposes
`/api/v1/projects/tasks/notifications`:

1. emits a `connected` control frame on accept,
2. on `{"action": "subscribe", "project_id": N}` → `subscribed` ack + the
   project's `TaskNotification`s (serialized via `msgspec.to_builtins`),
3. `{"action": "ping"}` → `pong`.

The same controller runs identically under both FastAPI (`ews_api.main`) and
Litestar (`ews_api.main_litestar`).

---

## Raw WebSocket vs python-socketio

The two operate at different layers. Raw WebSocket is the wire protocol
(RFC 6455). Socket.IO is a higher-level protocol layered *on top of* WebSocket
(with HTTP long-polling fallback) that adds connection management and messaging
features.

### What socket.io gives you out of the box

| # | Feature | Socket.IO | Raw WS equivalent |
|---|---------|-----------|-------------------|
| 1 | **Multi-server broadcast** | Redis/RabbitMQ manager (`AsyncRedisManager`); emit on server A reaches clients on server B | Build your own Redis pub/sub fan-out; in-memory tracking is single-process only |
| 2 | **Rooms** | `enter_room(sid, "project:2")` + `emit(..., room="project:2")` | Maintain `dict[str, set[WebSocket]]` and loop manually (~30 lines) |
| 3 | **Broadcast variants** | all / all-except-sender / room / namespace, one call each | Manual iteration with per-socket try/except (dead sockets throw) |
| 4 | **Transport fallback** | Negotiates WS, falls back to HTTP long-polling (proxies, old clients) | WS-only; connection fails if blocked |
| 5 | **Auto reconnection** | Client reconnects with backoff, re-emits queued messages | Write client reconnect logic yourself |
| 6 | **Ack callbacks** | Emit with callback; server invokes it; reply tied to that message | Invent correlation IDs and match replies yourself |
| 7 | **Event-based dispatch** | Named events: `socket.on("task.assigned", ...)` | One message stream; parse a `type`/`action` field and branch |
| 8 | **Namespaces + heartbeat** | Multiple logical channels per connection; built-in keepalive / dead-connection detection | Separate connections / your own routing; rely on ASGI ping-pong |

### What raw Starlette/Litestar WS keeps that socket.io loses

- Zero extra dependency; browser-native `WebSocket` client (no
  `socket.io-client` required).
- Flows through the `platform_core.http` controller/adapter abstraction.
  Socket.IO is a separate ASGI app you mount — it bypasses this layer.
- Standard tooling works (`wscat`, browser devtools); lower wire overhead;
  you fully own the protocol.

### Decision guidance

- **Single client listening to its own feed** (current state): raw WS is the
  right call. None of socket.io's features are in play, and it keeps WebSockets
  inside the controller abstraction.
- **One update → many watchers, single process**: raw WS + a small in-memory
  room registry covers #2/#3 while keeping the abstraction intact.
- **One update → many watchers across multiple server instances**: you need
  cross-server fan-out (#1). Either raw WS + Redis pub/sub, or socket.io with
  its Redis manager.

> Most teams that think they "need socket.io" actually need #1 (cross-server
> broadcast). If you'll only ever run one process, an in-memory registry is
> enough.

If socket.io is adopted, the clean integration is a **third adapter target**
(e.g. `register_socketio_controller`) rather than threading it through
`WebSocketSession` — its event/room model does not fit the plain
send/receive protocol.
