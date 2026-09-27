# WebSocket Testing Guide
First, install the required dependencies:

```bash
# Using pip
pip install 'python-socketio[client]' aiohttp

# Using uv (recommended for this project)
uv pip install 'python-socketio[client]' aiohttp
```

**Note for zsh users**: The quotes around `'python-socketio[client]'` are required in zsh shell to escape the square brackets.de explains how to test the WebSocket functionality in the eWorksuite API service.

## Overview

The eWorksuite API uses Socket.IO for WebSocket communication. The WebSocket server is integrated into the FastAPI application and provides real-time bidirectional communication.

### WebSocket Configuration

- **Mount Location**: `/ws`
- **Socket.IO Path**: `socket.io`
- **Full Path**: `http://localhost:8000/ws` or `http://localhost:8000/socket.io`
- **Events**:
  - `client_connected` - Client registration event
  - `user-message` - Server-to-client messages
  - `disconnect` - Disconnection event

## Testing Methods

### 1. Python Test Script

A comprehensive Python script for automated testing.

#### Installation

First, install the required dependencies:

```bash
# Using pip
pip install python-socketio[client] aiohttp

# Using uv (recommended for this project)
uv pip install 'python-socketio[client]' aiohttp
```

#### Usage

**Basic Test:**
```bash
python scripts/test_websocket.py
```

**With Custom Parameters:**
```bash
python scripts/test_websocket.py \
  --host localhost \
  --port 8000 \
  --user-uuid my-user-123
```

**Stress Test:**
```bash
python scripts/test_websocket.py \
  --test-type stress \
  --num-messages 50 \
  --user-uuid stress-test-user
```

#### Command Line Options

- `--host`: Server host (default: `localhost`)
- `--port`: Server port (default: `8000`)
- `--user-uuid`: User UUID for testing (default: `test-user-123`)
- `--test-type`: Type of test - `basic` or `stress` (default: `basic`)
- `--num-messages`: Number of messages for stress test (default: `10`)

#### Test Features

**Basic Test:**
- ✅ Connection establishment
- ✅ Client registration with UUID
- ✅ Receiving server messages
- ✅ Sending custom events
- ✅ Graceful disconnection

**Stress Test:**
- ✅ Multiple rapid messages
- ✅ Performance measurement
- ✅ Message delivery confirmation

### 2. HTML Test Client

A user-friendly web-based test client with a visual interface.

#### Usage

1. Make sure your eWorksuite API server is running:
   ```bash
   uv run uvicorn ews_api.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. Open the HTML test client:
   ```bash
   open scripts/test_websocket.html
   # or
   firefox scripts/test_websocket.html
   # or
   google-chrome scripts/test_websocket.html
   ```

3. Configure connection:
   - **Server URL**: `http://localhost:8000` (or your server URL)
   - **User UUID**: `test-user-123` (or any identifier)

4. Click **Connect** to establish connection

5. Click **Send Test Message** to send events

#### Features

- 🎨 Modern, responsive UI
- 📊 Real-time statistics (messages sent/received, session ID)
- 📝 Live message log with timestamps
- 🔌 Easy connect/disconnect controls
- 🧪 Test message sending
- 🗑️ Clear logs functionality

### 3. Using VS Code Task

You can run the test directly from VS Code.

Add this task to `.vscode/tasks.json`:

```json
{
    "label": "Test WebSocket",
    "type": "shell",
    "command": "python",
    "args": [
        "scripts/test_websocket.py",
        "--test-type",
        "basic"
    ],
    "problemMatcher": [],
    "presentation": {
        "reveal": "always",
        "panel": "new"
    }
}
```

Then run it via: `Terminal` → `Run Task` → `Test WebSocket`

## WebSocket Server Architecture

### Current Implementation

The WebSocket server is implemented in `services/ews_api/src/ews_api/main.py`:

```python
from core.websocket import WebSocketManager

# Initialize WebSocket manager
sio = WebSocketManager(app=app)

# Event handler for client connection
@app.sio.on("client_connected")
async def handle_client_connected(sid, data):
    print(f"handle_client_connected {sid} {data}")
    await app.sio.enter_room(sid, data["uuid"])
    await send_user_message(data["uuid"], {"message": "Hello guy!"})

# Event handler for disconnection
@app.sio.event
def disconnect(sid, reason):
    if reason == sio.reason.CLIENT_DISCONNECT:
        print("the client disconnected")
    elif reason == sio.reason.SERVER_DISCONNECT:
        print("the server disconnected the client")

# Send message to specific user
async def send_user_message(user_id, data):
    await app.sio.emit(event="user-message", data=data, room=user_id)
```

### WebSocketManager

Located in `libs/core/src/core/websocket/socketio.py`, provides:

- Socket.IO integration with FastAPI
- Redis pub/sub support for scaling (optional)
- Room management
- Event handling
- CORS configuration

## Testing Workflow

### 1. Start the Server

```bash
# Using the VS Code task
# Or manually:
cd /Users/thanhle/git/et/taas
uv run uvicorn ews_api.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Run Tests

```bash
# Python automated test
python scripts/test_websocket.py

# Or open HTML client
open scripts/test_websocket.html
```

### 3. Verify Results

Check for:
- ✅ Successful connection
- ✅ Client registration acknowledged
- ✅ Welcome message received
- ✅ Clean disconnection

## Expected Output

### Python Script Output

```
============================================================
Starting Basic WebSocket Test
============================================================

📝 Test 1: Connection

🔌 Connecting to http://localhost:8000...
   User UUID: test-user-123

[2025-10-02 10:30:45] ✅ Connected to server
Session ID: abc123def456
✅ Connection established successfully

📝 Test 2: Client Registration

📤 Sending 'client_connected' event...
✅ Event sent successfully

📝 Test 3: Receiving Messages

[2025-10-02 10:30:46] 📨 Received message:
  Data: {'message': 'Hello guy!'}

⏳ Waiting 3 seconds for messages...
✅ Received 1 message(s)

============================================================
Test Summary
============================================================
✅ Connected: Yes
📨 Messages received: 1

Received messages:
  1. {'message': 'Hello guy!'}
============================================================
```

## Troubleshooting

### Connection Refused

**Problem**: `Connection refused` error

**Solutions**:
1. Ensure server is running: `ps aux | grep uvicorn`
2. Check port availability: `lsof -i :8000`
3. Verify firewall settings

### No Messages Received

**Problem**: Connected but no messages arrive

**Solutions**:
1. Check server logs for errors
2. Verify event names match between client and server
3. Check room registration (UUID must match)

### CORS Errors (Browser)

**Problem**: CORS policy blocking connection

**Solutions**:
1. Check `cors_allowed_origins` in `WebSocketManager`
2. Verify server URL in HTML client
3. Try using `http://` instead of `https://` for local testing

### Redis Connection Issues

**Problem**: Redis-related errors

**Solutions**:
1. Check if Redis is needed: `settings.REDIS_HOST`
2. Start Redis if required: `docker-compose up -d redis`
3. Verify Redis connection: `redis-cli ping`

## Advanced Testing

### Multiple Concurrent Connections

Test multiple clients simultaneously:

```bash
# Terminal 1
python scripts/test_websocket.py --user-uuid user-1

# Terminal 2
python scripts/test_websocket.py --user-uuid user-2

# Terminal 3
python scripts/test_websocket.py --user-uuid user-3
```

### Load Testing

Use the stress test mode:

```bash
# Send 100 messages rapidly
python scripts/test_websocket.py --test-type stress --num-messages 100
```

### Custom Event Testing

Modify the Python script to add custom events:

```python
# In the script, add new event handlers
@self.sio.on("custom-event")
async def on_custom_event(data):
    print(f"Custom event received: {data}")

# Send custom events
await self.send_custom_message("custom-event", {
    "action": "test",
    "data": "custom payload"
})
```

## Integration with Your Application

### Adding New WebSocket Events

1. **Define event handler in `main.py`**:
   ```python
   @app.sio.on("your-event-name")
   async def handle_your_event(sid, data):
       # Handle the event
       await app.sio.emit("response-event", {"status": "received"}, room=sid)
   ```

2. **Test with Python client**:
   ```python
   await self.sio.emit("your-event-name", {"key": "value"})
   ```

3. **Test with HTML client**:
   ```javascript
   socket.emit('your-event-name', { key: 'value' });

   socket.on('response-event', (data) => {
       console.log('Response:', data);
   });
   ```

## Resources

- [Socket.IO Documentation](https://socket.io/docs/v4/)
- [python-socketio Documentation](https://python-socketio.readthedocs.io/)
- [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/)

## Support

For issues or questions:
1. Check server logs: `tail -f logs/app.log`
2. Enable debug mode in Python script
3. Use browser DevTools Network tab for HTML client
4. Review Socket.IO server logs
