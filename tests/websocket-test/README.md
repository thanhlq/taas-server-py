# WebSocket Testing Suite - Fixed & Ready! ✅

Complete testing suite for eWorksuite API WebSocket functionality with all issues resolved.

## 🎉 What's Been Fixed

1. ✅ **zsh compatibility** - Quoted package names for proper installation
2. ✅ **Path resolution** - Scripts work from any directory
3. ✅ **uv integration** - Uses `uv run python` for consistency
4. ✅ **Better error handling** - Clear error messages and recovery
5. ✅ **Interactive menu** - New test_suite.sh for guided testing

## 🚀 Quick Start (3 Simple Steps)

### Step 1: Install Dependencies
```bash
uv pip install 'python-socketio[client]' aiohttp
```

### Step 2: Start Server (in one terminal)
```bash
./start_server.sh
```

### Step 3: Run Tests (in another terminal)
```bash
./test_suite.sh
```

That's it! The interactive menu will guide you through all options.

## 📁 Files Overview

| File | Purpose | Usage |
|------|---------|-------|
| `test_suite.sh` | **Interactive test suite** ⭐ | `./test_suite.sh` |
| `start_server.sh` | Start WebSocket server | `./start_server.sh` |
| `run_websocket_test.sh` | Automated test runner | `./run_websocket_test.sh` |
| `test_websocket.py` | Python test client | `uv run python test_websocket.py` |
| `test_websocket.html` | Browser test client | `open test_websocket.html` |
| `websocket_examples.py` | Code examples | Reference |

## 🎯 Recommended: Use the Interactive Suite

```bash
./test_suite.sh
```

This gives you a menu with 6 options:
1. **Start the server** - Launches the WebSocket server
2. **Run basic test** - Quick connectivity test
3. **Run stress test** - Performance testing with 50 messages
4. **Open HTML client** - Browser-based testing
5. **Run all tests** - Complete test suite
6. **Exit** - Quit the suite

The suite automatically:
- ✅ Checks all dependencies
- ✅ Verifies test files exist
- ✅ Checks if server is running
- ✅ Guides you through each step

## 🧪 Testing Options

### Option 1: Interactive (Easiest)
```bash
./test_suite.sh
```
Choose from the menu!

### Option 2: Individual Scripts

**Basic test:**
```bash
./run_websocket_test.sh
```

**Stress test:**
```bash
./run_websocket_test.sh -t stress -n 100
```

**HTML client:**
```bash
./run_websocket_test.sh -t html
```

**Custom server:**
```bash
./run_websocket_test.sh -h 192.168.1.100 -p 8080
```

### Option 3: Direct Python

```bash
# Basic
uv run python test_websocket.py

# Stress
uv run python test_websocket.py --test-type stress --num-messages 50

# Custom
uv run python test_websocket.py --host localhost --port 8000 --user-uuid alice
```

### Option 4: HTML Browser Client

```bash
open test_websocket.html
```

## 🐛 Troubleshooting (All Fixed!)

### Issue 1: `zsh: no matches found: python-socketio[client]`
**Status:** ✅ FIXED
**Solution:** Scripts now use proper quoting: `'python-socketio[client]'`

### Issue 2: Server not running
**Status:** ✅ FIXED
**Solution:** Use `./start_server.sh` or the interactive suite will guide you

### Issue 3: Module not found
**Status:** ✅ FIXED
**Solution:** Scripts auto-check and install dependencies

### Issue 4: Script not found errors
**Status:** ✅ FIXED
**Solution:** All scripts now use absolute paths via `$SCRIPT_DIR`

### Issue 5: Permission denied
**Solution:**
```bash
chmod +x *.sh
```

## 📊 What Gets Tested

✅ WebSocket connection establishment
✅ Client registration with UUID
✅ Sending messages to server
✅ Receiving messages from server
✅ Room-based messaging
✅ Multiple concurrent connections
✅ Stress testing (100+ messages)
✅ Error handling & recovery
✅ Graceful disconnection
✅ Reconnection logic

## 📈 Expected Output

```
╔════════════════════════════════════════════════════════════╗
║         WebSocket Testing Suite - Complete Check          ║
╚════════════════════════════════════════════════════════════╝

▶ Checking dependencies...
✓ uv is installed
✓ python-socketio is installed
✓ aiohttp is installed

▶ Checking test files...
✓ test_websocket.py
✓ test_websocket.html
✓ run_websocket_test.sh
✓ start_server.sh

▶ Checking if server is running...
✓ Server is running on port 8000

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Available Test Options
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Start the server
2) Run basic WebSocket test
3) Run stress test
4) Open HTML test client
5) Run all automated tests
6) Exit

Select an option (1-6):
```

## 🎓 Usage Examples

### Example 1: First Time Setup
```bash
# 1. Install dependencies
uv pip install 'python-socketio[client]' aiohttp

# 2. Make scripts executable
chmod +x *.sh

# 3. Run interactive suite
./test_suite.sh

# 4. Choose option 1 to start server
# 5. Open another terminal
# 6. Run ./test_suite.sh again
# 7. Choose option 2 to run tests
```

### Example 2: Quick Test
```bash
# Terminal 1: Start server
./start_server.sh

# Terminal 2: Run test
./run_websocket_test.sh
```

### Example 3: Stress Testing
```bash
# Server already running
./run_websocket_test.sh -t stress -n 200
```

### Example 4: Multiple Users
```bash
# Terminal 1
uv run python test_websocket.py --user-uuid alice

# Terminal 2
uv run python test_websocket.py --user-uuid bob

# Terminal 3
uv run python test_websocket.py --user-uuid charlie
```

### Example 5: Manual Testing
```bash
# Open browser client
open test_websocket.html

# Use UI to:
# - Connect/disconnect
# - Send custom messages
# - Monitor statistics
# - Debug issues
```

## 🔍 Debugging Tips

### 1. Check Everything
```bash
./test_suite.sh
# It checks dependencies, files, and server status
```

### 2. Enable Verbose Logging
Edit `test_websocket.py`:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 3. Monitor Server
```bash
# Watch server logs
tail -f /Users/thanhle/git/et/taas/logs/app.log
```

### 4. Browser DevTools
For HTML client:
- Press F12
- Go to Network tab
- Filter by WS (WebSocket)
- See real-time traffic

### 5. Test Connection Manually
```bash
curl http://localhost:8000/docs
```

## 📚 Additional Documentation

- **WEBSOCKET_TESTING.md** - Complete testing guide
- **WEBSOCKET_QUICK_REF.md** - Quick command reference
- **WEBSOCKET_ARCHITECTURE.md** - System architecture diagrams
- **INSTALL_NOTES.md** - Detailed installation help
- **websocket_examples.py** - 10+ code examples

## 🎯 Test Scenarios Covered

### Basic Connectivity
```bash
./test_suite.sh → Option 2
```
Tests: Connect, register, receive message, disconnect

### Performance
```bash
./run_websocket_test.sh -t stress -n 100
```
Tests: 100 rapid messages, latency, throughput

### Multi-User
```bash
# Run in 3 terminals simultaneously
```
Tests: Concurrent connections, room isolation

### Manual QA
```bash
open test_websocket.html
```
Tests: Interactive UI testing, debugging

## 🚦 Status Indicators

When you run tests, you'll see:
- ✅ **Green checkmarks** - Success
- ⚠️ **Yellow warnings** - Non-critical issues
- ✗ **Red X** - Errors that need attention
- ℹ **Blue info** - Helpful information

## 🎉 Success Criteria

Your WebSocket is working correctly when:
1. ✅ Server starts without errors
2. ✅ Client connects successfully
3. ✅ Welcome message is received
4. ✅ Custom events work
5. ✅ Stress test completes without drops
6. ✅ Multiple users can connect
7. ✅ HTML client shows real-time updates

## 🤝 Next Steps

1. ✅ **Run the test suite** - Verify everything works
2. 📖 **Read the examples** - See `websocket_examples.py`
3. 🔧 **Add custom events** - Extend your application
4. 🚀 **Deploy** - You're ready for production!

## 💡 Pro Tips

- Use `./test_suite.sh` for first-time setup
- Keep server running in one terminal
- Use HTML client for manual testing
- Run stress tests before deployment
- Check server logs when debugging
- Try multiple concurrent connections

## 📞 Need Help?

1. Run `./test_suite.sh` - It checks everything
2. Check `INSTALL_NOTES.md` - Common installation issues
3. Review server logs - See actual errors
4. Try HTML client - Visual debugging
5. Check documentation - Detailed guides available

---

**Version:** 2.0 (All Issues Fixed!)
**Last Updated:** October 2, 2025
**Status:** ✅ Production Ready
