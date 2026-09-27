#!/usr/bin/env python3
"""
WebSocket Test Script for eWorksuite API

This script tests the WebSocket functionality using Socket.IO client.
It connects to the server, sends messages, and receives responses.

Usage:
    python scripts/test_websocket.py

    # With custom parameters:
    python scripts/test_websocket.py --host localhost --port 8191 --user-uuid test-user-123
"""

import argparse
import asyncio
import sys
from datetime import datetime
from typing import Optional

import socketio


class WebSocketTester:
    """WebSocket test client using Socket.IO"""

    def __init__(
        self,
        host: str = 'localhost',
        port: int = 8191,
        user_uuid: str = 'test-user-123',
    ):
        self.host = host
        self.port = port
        self.user_uuid = user_uuid
        self.base_url = f'http://{host}:{port}'
        self.sio: Optional[socketio.AsyncClient] = None
        self.connected = False
        self.messages_received = []

    async def setup_client(self):
        """Initialize the Socket.IO client with event handlers"""
        self.sio = socketio.AsyncClient(
            logger=True,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=3,
            reconnection_delay=1,
            reconnection_delay_max=5,
        )

        # Register event handlers
        @self.sio.event
        async def connect():
            self.connected = True
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f'\n[{timestamp}] ✅ Connected to server')
            print(f'Session ID: {self.sio.sid}')

        @self.sio.event
        async def disconnect():
            self.connected = False
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f'\n[{timestamp}] ❌ Disconnected from server')

        @self.sio.event
        async def connect_error(data):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f'\n[{timestamp}] ⚠️  Connection error: {data}')

        @self.sio.on('user-message')
        async def on_user_message(data):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f'\n[{timestamp}] 📨 Received message:')
            print(f'  Data: {data}')
            self.messages_received.append(data)

        @self.sio.on('*')
        async def catch_all(event, data):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{timestamp}] 🔔 Event '{event}' received:")
            print(f'  Data: {data}')

    async def connect(self):
        """Connect to the WebSocket server"""
        print(f'\n🔌 Connecting to {self.base_url}...')
        print(f'   User UUID: {self.user_uuid}')

        try:
            # Connect using the /ws endpoint (mount_location from WebSocketManager)
            await self.sio.connect(
                self.base_url,
                socketio_path='socket.io',
                wait_timeout=10,
            )

            # Wait a moment for connection to establish
            await asyncio.sleep(0.5)

            if self.connected:
                print('✅ Connection established successfully')
                return True
            else:
                print('❌ Connection failed')
                return False

        except Exception as e:
            print(f'❌ Connection error: {e}')
            return False

    async def send_client_connected(self):
        """Send client_connected event to register with the server"""
        if not self.connected:
            print('❌ Not connected. Cannot send message.')
            return False

        print(f"\n📤 Sending 'client_connected' event...")
        try:
            await self.sio.emit('client_connected', {'uuid': self.user_uuid})
            print('✅ Event sent successfully')

            # Wait for server response
            await asyncio.sleep(1)
            return True
        except Exception as e:
            print(f'❌ Error sending event: {e}')
            return False

    async def send_custom_message(self, event: str, data: dict):
        """Send a custom message to the server"""
        if not self.connected:
            print('❌ Not connected. Cannot send message.')
            return False

        print(f"\n📤 Sending '{event}' event...")
        print(f'   Data: {data}')
        try:
            await self.sio.emit(event, data)
            print('✅ Event sent successfully')
            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            print(f'❌ Error sending event: {e}')
            return False

    async def wait_for_messages(self, duration: int = 5):
        """Wait for incoming messages"""
        print(f'\n⏳ Waiting {duration} seconds for messages...')
        await asyncio.sleep(duration)
        print(f'✅ Received {len(self.messages_received)} message(s)')

    async def disconnect(self):
        """Disconnect from the server"""
        if self.sio and self.connected:
            print('\n🔌 Disconnecting...')
            await self.sio.disconnect()
            await asyncio.sleep(0.5)
            print('✅ Disconnected')

    async def run_basic_test(self):
        """Run a basic WebSocket test"""
        print('\n' + '=' * 60)
        print('Starting Basic WebSocket Test')
        print('=' * 60)

        await self.setup_client()

        # Test 1: Connect
        print('\n📝 Test 1: Connection')
        if not await self.connect():
            print('❌ Connection test failed')
            return False

        # Test 2: Register client
        print('\n📝 Test 2: Client Registration')
        if not await self.send_client_connected():
            print('❌ Client registration failed')
            await self.disconnect()
            return False

        # Test 3: Wait for server message
        print('\n📝 Test 3: Receiving Messages')
        await self.wait_for_messages(3)

        # Test 4: Send custom message (if you have custom events)
        print('\n📝 Test 4: Custom Message')
        await self.send_custom_message(
            'test-event',
            {
                'message': 'Hello from test client',
                'timestamp': datetime.now().isoformat(),
            },
        )

        # Wait for any responses
        await self.wait_for_messages(2)

        # Disconnect
        await self.disconnect()

        print('\n' + '=' * 60)
        print('Test Summary')
        print('=' * 60)
        print(f'✅ Connected: Yes')
        print(f'📨 Messages received: {len(self.messages_received)}')
        if self.messages_received:
            print('\nReceived messages:')
            for i, msg in enumerate(self.messages_received, 1):
                print(f'  {i}. {msg}')
        print('=' * 60)

        return True

    async def run_stress_test(self, num_messages: int = 10):
        """Run a stress test by sending multiple messages"""
        print('\n' + '=' * 60)
        print(f'Starting Stress Test ({num_messages} messages)')
        print('=' * 60)

        await self.setup_client()

        if not await self.connect():
            print('❌ Connection failed')
            return False

        if not await self.send_client_connected():
            print('❌ Client registration failed')
            await self.disconnect()
            return False

        print(f'\n📤 Sending {num_messages} messages...')
        for i in range(num_messages):
            await self.send_custom_message(
                f'test-message-{i}',
                {
                    'index': i,
                    'timestamp': datetime.now().isoformat(),
                    'uuid': self.user_uuid,
                },
            )
            await asyncio.sleep(0.1)  # Small delay between messages

        print('\n⏳ Waiting for responses...')
        await self.wait_for_messages(5)

        await self.disconnect()

        print('\n' + '=' * 60)
        print('Stress Test Summary')
        print('=' * 60)
        print(f'📤 Messages sent: {num_messages}')
        print(f'📨 Messages received: {len(self.messages_received)}')
        print('=' * 60)

        return True


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Test WebSocket functionality for eWorksuite API'
    )
    parser.add_argument(
        '--host', default='localhost', help='Server host (default: localhost)'
    )
    parser.add_argument(
        '--port', type=int, default=8191, help='Server port (default: 8191)'
    )
    parser.add_argument(
        '--user-uuid',
        default='test-user-123',
        help='User UUID for testing (default: test-user-123)',
    )
    parser.add_argument(
        '--test-type',
        choices=['basic', 'stress'],
        default='basic',
        help='Type of test to run (default: basic)',
    )
    parser.add_argument(
        '--num-messages',
        type=int,
        default=10,
        help='Number of messages for stress test (default: 10)',
    )

    args = parser.parse_args()

    tester = WebSocketTester(host=args.host, port=args.port, user_uuid=args.user_uuid)

    try:
        if args.test_type == 'basic':
            success = await tester.run_basic_test()
        else:
            success = await tester.run_stress_test(args.num_messages)

        if success:
            print('\n✅ All tests completed successfully!')
            sys.exit(0)
        else:
            print('\n❌ Tests failed!')
            sys.exit(1)

    except KeyboardInterrupt:
        print('\n\n⚠️  Test interrupted by user')
        if tester.sio and tester.connected:
            await tester.disconnect()
        sys.exit(1)
    except Exception as e:
        print(f'\n❌ Test error: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
