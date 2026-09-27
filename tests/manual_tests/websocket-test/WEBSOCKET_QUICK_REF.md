# WebSocket Quick Reference

## Quick Start

### 1. Install Dependencies
```bash
uv pip install python-socketio[client] aiohttp
```

### 2. Start Server
```bash
uv run uvicorn ews_api.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Run Test
```bash
# Python test
python scripts/test_websocket.py

# HTML test
open scripts/test_websocket.html
```

## Connection Details

| Property | Value |
|----------|-------|
| Base URL | `http://localhost:8000` |
| WebSocket Path | `/ws` |
| Socket.IO Path | `socket.io` |
| Default Port | 8000 |

## Events

### Client → Server

| Event | Payload | Description |
|-------|---------|-------------|
| `client_connected` | `{"uuid": "user-id"}` | Register client with UUID |
| Custom events | Any JSON | Your custom events |

### Server → Client

| Event | Payload | Description |
|-------|---------|-------------|
| `user-message` | `{"message": "..."}` | Messages to specific user |
| `connect` | Auto | Connection established |
| `disconnect` | Auto | Connection closed |

## Python Test Script

### Basic Usage
```bash
python scripts/test_websocket.py
```

### Options
```bash
--host localhost          # Server host
--port 8000              # Server port
--user-uuid test-123     # User identifier
--test-type basic        # Test type: basic|stress
--num-messages 10        # Number of messages (stress test)
```

### Examples
```bash
# Custom server
python scripts/test_websocket.py --host 192.168.1.100 --port 8080

# Stress test
python scripts/test_websocket.py --test-type stress --num-messages 50

# Different user
python scripts/test_websocket.py --user-uuid alice-456
```

## HTML Test Client

### Access
```bash
open scripts/test_websocket.html
```

### Features
- 🔌 Connect/Disconnect controls
- 📤 Send test messages
- 📊 Real-time statistics
- 📝 Live message log
- 🎨 Visual interface

## Code Examples

### Python Client
```python
import socketio

# Create client
sio = socketio.AsyncClient()

# Connect
await sio.connect('http://localhost:8000')

# Register
await sio.emit('client_connected', {'uuid': 'my-user'})

# Listen for messages
@sio.on('user-message')
async def on_message(data):
    print(f"Received: {data}")

# Send custom event
await sio.emit('my-event', {'key': 'value'})

# Disconnect
await sio.disconnect()
```

### JavaScript Client
```javascript
// Connect
const socket = io('http://localhost:8000', {
    path: '/socket.io'
});

// Register
socket.on('connect', () => {
    socket.emit('client_connected', { uuid: 'my-user' });
});

// Listen
socket.on('user-message', (data) => {
    console.log('Received:', data);
});

// Send
socket.emit('my-event', { key: 'value' });

// Disconnect
socket.disconnect();
```

### Server Side (FastAPI)
```python
from core.websocket import WebSocketManager

app = FastAPI()
sio = WebSocketManager(app=app)

# Handle event
@app.sio.on("client_connected")
async def handle_client_connected(sid, data):
    await app.sio.enter_room(sid, data["uuid"])
    await send_message(data["uuid"], {"msg": "Welcome!"})

# Send to room
async def send_message(room, data):
    await app.sio.emit("user-message", data, room=room)

# Send to specific client
async def send_to_client(sid, data):
    await app.sio.emit("user-message", data, to=sid)
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check if server is running on correct port |
| No messages received | Verify event names match client/server |
| CORS error | Check `cors_allowed_origins` setting |
| Redis error | Ensure Redis is running or disable in settings |

## Common Commands

```bash
# Check if server is running
ps aux | grep uvicorn

# Check port usage
lsof -i :8000

# View server logs
tail -f logs/app.log

# Test with curl (HTTP endpoint)
curl http://localhost:8000/

# Check Redis connection
redis-cli ping
```

## Test Checklist

- [ ] Server is running
- [ ] Client can connect
- [ ] `client_connected` event works
- [ ] Welcome message received
- [ ] Custom events work
- [ ] Can disconnect cleanly
- [ ] Multiple clients work
- [ ] Room messaging works

## Performance Tips

- Use connection pooling for multiple clients
- Enable Redis for horizontal scaling
- Monitor memory usage with many connections
- Use namespaces for organizing events
- Implement reconnection logic on client side

## Links

- Python Script: `scripts/test_websocket.py`
- HTML Client: `scripts/test_websocket.html`
- Full Guide: `scripts/WEBSOCKET_TESTING.md`
- Server Code: `services/ews_api/src/ews_api/main.py`
- WebSocket Manager: `libs/core/src/core/websocket/socketio.py`
