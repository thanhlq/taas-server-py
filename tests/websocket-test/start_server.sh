#!/bin/bash
# Start eWorksuite WebSocket Server
# Usage: ./start_server.sh [port]

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

PORT="${1:-8000}"
PROJECT_ROOT="/Users/thanhle/git/et/taas"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Starting eWorksuite API Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${GREEN}✓${NC} Port: ${PORT}"
echo -e "${GREEN}✓${NC} WebSocket endpoint: ws://localhost:${PORT}/ws"
echo -e "${GREEN}✓${NC} API docs: http://localhost:${PORT}/docs"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

cd "$PROJECT_ROOT"
uv run uvicorn eworksuite_api.main:app --reload --host 0.0.0.0 --port "$PORT"
