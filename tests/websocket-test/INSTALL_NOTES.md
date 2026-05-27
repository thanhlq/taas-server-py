# Installation Notes

## Quick Install

### For zsh users (macOS default shell):

```bash
uv pip install 'python-socketio[client]' aiohttp
```

### For bash users:

```bash
uv pip install python-socketio[client] aiohttp
```

## Why the quotes?

In **zsh** (the default shell on macOS), square brackets `[]` have special meaning for pattern matching. You need to:
- **Option 1**: Quote the package name: `'python-socketio[client]'`
- **Option 2**: Escape the brackets: `python-socketio\[client\]`
- **Option 3**: Use double quotes: `"python-socketio[client]"`

## Common Errors

### Error: `zsh: no matches found: python-socketio[client]`

**Cause**: Square brackets not escaped in zsh

**Fix**: Add quotes:
```bash
uv pip install 'python-socketio[client]' aiohttp
```

### Error: `command not found: uv`

**Cause**: uv is not installed

**Fix**: Install uv first:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or use pip directly:
```bash
pip install 'python-socketio[client]' aiohttp
```

## Verification

After installation, verify it worked:

```bash
python3 -c "import socketio; print(f'Socket.IO version: {socketio.__version__}')"
```

Expected output:
```
Socket.IO version: 5.x.x
```

## Alternative Installation Methods

### Using pip directly:
```bash
pip install 'python-socketio[client]' aiohttp
```

### Using conda:
```bash
conda install -c conda-forge python-socketio aiohttp
```

### Using poetry:
```bash
poetry add "python-socketio[client]" aiohttp
```

## Next Steps

Once installed, you can run the WebSocket tests:

```bash
# Basic test
python scripts/test_websocket.py

# Or use the shell script
./scripts/run_websocket_test.sh
```
