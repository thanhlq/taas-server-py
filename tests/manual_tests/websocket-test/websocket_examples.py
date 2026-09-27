"""
Example: Adding Custom WebSocket Events

This file demonstrates how to add custom WebSocket events to your application.
Copy the relevant code snippets to your main.py or create separate event handlers.
"""

from core.websocket import WebSocketManager
from fastapi import FastAPI

# Initialize your app and WebSocket manager
app = FastAPI()
sio = WebSocketManager(app=app)


# ============================================================================
# EXAMPLE 1: Simple Echo Event
# ============================================================================


@app.sio.on('echo')
async def handle_echo(sid, data):
    """
    Echo back whatever the client sends.

    Client sends: {"message": "Hello"}
    Server responds: {"echo": "Hello", "timestamp": "..."}
    """
    from datetime import datetime

    response = {
        'echo': data.get('message', ''),
        'timestamp': datetime.now().isoformat(),
        'original': data,
    }
    await app.sio.emit('echo_response', response, to=sid)


# ============================================================================
# EXAMPLE 2: Broadcast to All Users
# ============================================================================


@app.sio.on('broadcast_message')
async def handle_broadcast(sid, data):
    """
    Broadcast a message to all connected clients.

    Client sends: {"message": "Important announcement"}
    Server broadcasts to everyone
    """
    await app.sio.emit('broadcast', {'message': data.get('message'), 'from_sid': sid})


# ============================================================================
# EXAMPLE 3: Private Message Between Users
# ============================================================================


@app.sio.on('private_message')
async def handle_private_message(sid, data):
    """
    Send private message from one user to another.

    Client sends: {
        "to_uuid": "user-123",
        "message": "Hello privately"
    }
    """
    to_uuid = data.get('to_uuid')
    message = data.get('message')
    from_uuid = data.get('from_uuid')

    # Send to recipient's room (using UUID)
    await app.sio.emit(
        'private_message', {'from': from_uuid, 'message': message}, room=to_uuid
    )

    # Confirm to sender
    await app.sio.emit('message_sent', {'to': to_uuid, 'status': 'delivered'}, to=sid)


# ============================================================================
# EXAMPLE 4: Join/Leave Channels
# ============================================================================


@app.sio.on('join_channel')
async def handle_join_channel(sid, data):
    """
    Join a topic/channel for group messaging.

    Client sends: {"channel": "general", "uuid": "user-123"}
    """
    channel = data.get('channel', 'default')
    await app.sio.enter_room(sid, f'channel:{channel}')

    # Notify others in the channel
    await app.sio.emit(
        'user_joined',
        {'uuid': data.get('uuid'), 'channel': channel},
        room=f'channel:{channel}',
        skip_sid=sid,
    )

    # Confirm to user
    await app.sio.emit(
        'channel_joined', {'channel': channel, 'status': 'success'}, to=sid
    )


@app.sio.on('leave_channel')
async def handle_leave_channel(sid, data):
    """Leave a channel."""
    channel = data.get('channel', 'default')
    await app.sio.leave_room(sid, f'channel:{channel}')

    # Notify others
    await app.sio.emit(
        'user_left',
        {'uuid': data.get('uuid'), 'channel': channel},
        room=f'channel:{channel}',
    )


@app.sio.on('channel_message')
async def handle_channel_message(sid, data):
    """
    Send message to all users in a channel.

    Client sends: {
        "channel": "general",
        "message": "Hello channel!",
        "uuid": "user-123"
    }
    """
    channel = data.get('channel', 'default')
    await app.sio.emit(
        'channel_message',
        {'from': data.get('uuid'), 'message': data.get('message'), 'channel': channel},
        room=f'channel:{channel}',
        skip_sid=sid,
    )


# ============================================================================
# EXAMPLE 5: Typing Indicator
# ============================================================================


@app.sio.on('typing_start')
async def handle_typing_start(sid, data):
    """
    User started typing.

    Client sends: {"uuid": "user-123", "room": "chat-room-456"}
    """
    room = data.get('room')
    await app.sio.emit(
        'user_typing',
        {'uuid': data.get('uuid'), 'typing': True},
        room=room,
        skip_sid=sid,
    )


@app.sio.on('typing_stop')
async def handle_typing_stop(sid, data):
    """User stopped typing."""
    room = data.get('room')
    await app.sio.emit(
        'user_typing',
        {'uuid': data.get('uuid'), 'typing': False},
        room=room,
        skip_sid=sid,
    )


# ============================================================================
# EXAMPLE 6: Presence/Status Updates
# ============================================================================


@app.sio.on('update_status')
async def handle_status_update(sid, data):
    """
    Update user online status.

    Client sends: {"uuid": "user-123", "status": "online|away|busy|offline"}
    """
    uuid = data.get('uuid')
    status = data.get('status', 'online')

    # Broadcast status to all users (or specific groups)
    await app.sio.emit('status_changed', {'uuid': uuid, 'status': status})


# ============================================================================
# EXAMPLE 7: File/Media Sharing Notification
# ============================================================================


@app.sio.on('share_file')
async def handle_file_share(sid, data):
    """
    Notify users about file sharing.

    Client sends: {
        "to_uuid": "user-123",
        "file_url": "https://...",
        "filename": "document.pdf",
        "from_uuid": "user-456"
    }
    """
    to_uuid = data.get('to_uuid')
    await app.sio.emit(
        'file_received',
        {
            'from': data.get('from_uuid'),
            'file_url': data.get('file_url'),
            'filename': data.get('filename'),
            'size': data.get('size'),
        },
        room=to_uuid,
    )


# ============================================================================
# EXAMPLE 8: Real-time Notifications
# ============================================================================


async def send_notification(user_uuid: str, notification_type: str, data: dict):
    """
    Helper function to send notifications to users.
    Call this from anywhere in your app.
    """
    await app.sio.emit(
        'notification',
        {
            'type': notification_type,
            'data': data,
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        },
        room=user_uuid,
    )


# Example usage in your business logic:
async def on_order_completed(order_id: str, user_uuid: str):
    """Example: Notify user when order is completed"""
    await send_notification(
        user_uuid,
        'order_completed',
        {'order_id': order_id, 'message': 'Your order has been completed!'},
    )


# ============================================================================
# EXAMPLE 9: Request-Response Pattern
# ============================================================================


@app.sio.on('get_online_users')
async def handle_get_online_users(sid, data):
    """
    Return list of online users.
    Uses synchronous response pattern.
    """
    # Get all connected sessions (this is an example)
    # In production, you'd query a database or cache
    online_users = [
        {'uuid': 'user-1', 'name': 'Alice', 'status': 'online'},
        {'uuid': 'user-2', 'name': 'Bob', 'status': 'away'},
    ]

    return online_users  # Direct return sends response to caller


# ============================================================================
# EXAMPLE 10: Error Handling
# ============================================================================


@app.sio.on('risky_operation')
async def handle_risky_operation(sid, data):
    """
    Example with error handling.
    """
    try:
        # Perform operation
        result = await perform_operation(data)

        await app.sio.emit('operation_success', {'result': result}, to=sid)

    except ValueError as e:
        # Send error to client
        await app.sio.emit(
            'operation_error', {'error': str(e), 'code': 'VALIDATION_ERROR'}, to=sid
        )

    except Exception as e:
        # Generic error
        await app.sio.emit(
            'operation_error',
            {'error': 'An unexpected error occurred', 'code': 'INTERNAL_ERROR'},
            to=sid,
        )


async def perform_operation(data):
    """Dummy operation for example"""
    if not data.get('required_field'):
        raise ValueError('required_field is missing')
    return {'success': True}


# ============================================================================
# TESTING YOUR CUSTOM EVENTS
# ============================================================================

"""
Test your custom events using the Python test script:

1. Modify scripts/test_websocket.py and add:

   async def test_custom_events(self):
       # Test echo
       await self.sio.emit("echo", {"message": "test"})
       
       # Test broadcast
       await self.sio.emit("broadcast_message", {
           "message": "Hello everyone!"
       })
       
       # Test private message
       await self.sio.emit("private_message", {
           "to_uuid": "user-123",
           "from_uuid": self.user_uuid,
           "message": "Private hello"
       })

2. Or test using the HTML client by adding to the JavaScript:

   socket.emit('echo', { message: 'Hello' });
   
   socket.on('echo_response', (data) => {
       console.log('Echo response:', data);
   });

3. Or test with curl/httpie for HTTP endpoints.
"""

# ============================================================================
# BACKGROUND TASKS
# ============================================================================


async def periodic_update_task():
    """
    Example background task that sends periodic updates.
    Start this in your lifespan context.
    """
    import asyncio
    from datetime import datetime

    while True:
        await asyncio.sleep(60)  # Every minute

        # Broadcast server time to all connected clients
        await app.sio.emit('server_time', {'timestamp': datetime.now().isoformat()})


# To start background task, add to lifespan in main.py:
"""
@asynccontextmanager
async def lifespan(application: FastAPI):
    # Start background tasks
    task = asyncio.create_task(periodic_update_task())
    
    yield
    
    # Cleanup
    task.cancel()
"""
