# Manual testing the Socket.IO feed with a JavaScript client

How to manually exercise the project task-notification Socket.IO endpoint
using the official `socket.io-client` JS library (browser or Node.js).

See [WEBSOCKETS.md](./WEBSOCKETS.md) for the architecture and the raw-WebSocket
vs Socket.IO decision.

## 1. Start the server

Socket.IO is the default transport in `ews_api`. Run either framework — the
behaviour is identical:

```bash
# FastAPI
uv run --prerelease=allow python -m ews_api.main

# or Litestar
uv run --prerelease=allow python -m ews_api.main_litestar
```

The server listens on `http://0.0.0.0:8191` (reachable as
`http://127.0.0.1:8191`). Socket.IO is mounted at the default path
`/socket.io` on the **root** of the app — it is *not* under
`/api/v1/projects`, because Socket.IO is its own ASGI app, not a controller
route.

## 2. Version compatibility (important)

The server uses `python-socketio==5.16.2`, which speaks the **Socket.IO v5
protocol (Engine.IO v4)**. You must use a compatible JS client:

| Server (`python-socketio`) | Browser/Node client (`socket.io-client`) |
|----------------------------|-------------------------------------------|
| 5.x                        | **4.x**                                   |

Using `socket.io-client` v2/v3 will fail the handshake.

## 3. Event reference (what the server speaks)

Default namespace `/`. The client drives the exchange by emitting `subscribe`
and `ping`.

| Direction | Event          | Payload                                                                 |
|-----------|----------------|-------------------------------------------------------------------------|
| → client  | `connected`    | `{ "channel": "project-tasks" }` (emitted automatically on connect)     |
| client →  | `subscribe`    | `{ "project_id": 2 }`                                                    |
| → client  | `subscribed`   | `{ "project_id": 2 }`                                                    |
| → client  | `task.created` | `{ event, projectId, taskId, title, occurredAt }`                       |
| → client  | `task.assigned`| `{ event, projectId, taskId, title, assignee, occurredAt }`             |
| client →  | `ping`         | `{}`                                                                     |
| → client  | `pong`         | `{}`                                                                     |

Subscribing also joins the socket to room `project:<id>` server-side, so a
future task update can be broadcast to every subscriber of that project.

## 4. Browser (quickest check)

Create `socketio_test.html` and open it in a browser; watch the console.

```html
<!doctype html>
<html>
  <head>
    <!-- Must be a v4 client to match python-socketio 5.x -->
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
  </head>
  <body>
    <h1>Socket.IO task-notification test — open the console</h1>
    <script>
      const socket = io("http://127.0.0.1:8191", {
        transports: ["websocket"], // skip long-polling; optional
      });

      socket.on("connect", () => {
        console.log("connected, sid =", socket.id);
        // Subscribe to project 2's task feed
        socket.emit("subscribe", { project_id: 2 });
        // Round-trip ping
        socket.emit("ping", {});
      });

      socket.on("connected",     (d) => console.log("connected event:", d));
      socket.on("subscribed",    (d) => console.log("subscribed:", d));
      socket.on("task.created",  (d) => console.log("task.created:", d));
      socket.on("task.assigned", (d) => console.log("task.assigned:", d));
      socket.on("pong",          (d) => console.log("pong:", d));

      socket.on("connect_error", (e) => console.error("connect_error:", e.message));
      socket.on("disconnect",    (r) => console.log("disconnected:", r));
    </script>
  </body>
</html>
```

Expected console output:

```
connected, sid = <id>
connected event: { channel: 'project-tasks' }
subscribed: { project_id: 2 }
task.created: { event: 'task.created', projectId: 2, taskId: 101, ... }
task.assigned: { event: 'task.assigned', projectId: 2, ..., assignee: 'thanhlq@msn.com' }
pong: {}
```

CORS is open (`cors_allowed_origins='*'` in `build_socketio_server`), so
opening the file directly (``file://``) or from any origin works in dev.

## 5. Node.js

```bash
mkdir sio-test && cd sio-test
npm init -y
npm install socket.io-client@4
```

`test.mjs`:

```js
import { io } from "socket.io-client";

const socket = io("http://127.0.0.1:8191", { transports: ["websocket"] });

socket.on("connect", () => {
  console.log("connected, sid =", socket.id);
  socket.emit("subscribe", { project_id: 2 });
  socket.emit("ping", {});
});

socket.on("connected",     (d) => console.log("connected event:", d));
socket.on("subscribed",    (d) => console.log("subscribed:", d));
socket.on("task.created",  (d) => console.log("task.created:", d));
socket.on("task.assigned", (d) => console.log("task.assigned:", d));
socket.on("pong",          (d) => {
  console.log("pong:", d);
  socket.disconnect();
  process.exit(0);
});

socket.on("connect_error", (e) => console.error("connect_error:", e.message));
```

Run it:

```bash
node test.mjs
```

## 6. Using acknowledgement callbacks (optional)

The current handlers reply by emitting separate events, but Socket.IO also
supports request/response acks. If you add ack-returning handlers server-side
later, the client side looks like:

```js
socket.emit("subscribe", { project_id: 2 }, (ack) => {
  console.log("server ack:", ack);
});
```

## 7. Connecting to a non-default path or namespace

If the server is mounted with a custom `socketio_path` (see
`create_socketio_asgi_app(..., socketio_path="ws")`):

```js
const socket = io("http://127.0.0.1:8191", { path: "/ws" });
```

For a custom namespace (e.g. handlers registered with
`@socketio_event("subscribe", namespace="/projects")`):

```js
const socket = io("http://127.0.0.1:8191/projects");
```

## 8. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `connect_error: xhr poll error` / handshake fails | Client major version ≠ 4, or wrong host/port |
| Connects but no `connected`/`subscribed` events | Wrong namespace, or emitting before `connect` fires |
| 404 on `/socket.io/?EIO=4...` | Server not wrapped with `create_socketio_asgi_app`, or wrong `path` |
| CORS error in browser | Server built without `cors_allowed_origins` (default is `'*'`) |
| Raw `wscat ws://.../socket.io` does nothing useful | Socket.IO ≠ raw WebSocket; you must use `socket.io-client` |
