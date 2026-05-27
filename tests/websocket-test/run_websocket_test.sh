#!/bin/bash
# WebSocket Test Runner for eWorksuite API
# Usage: ./scripts/run_websocket_test.sh [test-type] [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
HOST="localhost"
PORT="8000"
USER_UUID="test-user-$(date +%s)"
TEST_TYPE="basic"
NUM_MESSAGES="10"

# Print colored message
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  WebSocket Test Runner - eWorksuite API"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${NC}"
}

# Check if server is running
check_server() {
    print_info "Checking if server is running on ${HOST}:${PORT}..."

    if curl -s "http://${HOST}:${PORT}/docs" > /dev/null 2>&1; then
        print_success "Server is running"
        return 0
    else
        print_error "Server is not running on ${HOST}:${PORT}"
        print_info "Start the server with: uv run uvicorn eworksuite_api.main:app --reload --host 0.0.0.0 --port ${PORT}"
        return 1
    fi
}

# Check dependencies
check_dependencies() {
    print_info "Checking dependencies..."

    # Check if we can import socketio in the uv environment
    if ! uv run python -c "import socketio" 2>/dev/null; then
        print_warning "python-socketio not installed"
        print_info "Installing dependencies..."
        # Fix for zsh: quote the package name to escape square brackets
        uv pip install 'python-socketio[client]' aiohttp
        if [ $? -eq 0 ]; then
            print_success "Dependencies installed"
        else
            print_error "Failed to install dependencies"
            print_info "Try manually: uv pip install 'python-socketio[client]' aiohttp"
            return 1
        fi
    else
        print_success "Dependencies are installed"
    fi
}

# Run Python test
run_python_test() {
    print_info "Running Python WebSocket test..."
    echo ""

    # Get the script directory to ensure correct path
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

    # Use uv run to execute in the project environment
    uv run python "${SCRIPT_DIR}/test_websocket.py" \
        --host "$HOST" \
        --port "$PORT" \
        --user-uuid "$USER_UUID" \
        --test-type "$TEST_TYPE" \
        --num-messages "$NUM_MESSAGES"
}

# Open HTML test client
open_html_client() {
    print_info "Opening HTML test client..."

    # Get the script directory to ensure correct path
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    local html_file="${SCRIPT_DIR}/test_websocket.html"

    if [ -f "$html_file" ]; then
        # Try to open with default browser
        if command -v open &> /dev/null; then
            # macOS
            open "$html_file"
        elif command -v xdg-open &> /dev/null; then
            # Linux
            xdg-open "$html_file"
        elif command -v start &> /dev/null; then
            # Windows
            start "$html_file"
        else
            print_warning "Could not open browser automatically"
            print_info "Please open: file://$(pwd)/$html_file"
        fi
        print_success "HTML client opened"
    else
        print_error "HTML file not found: $html_file"
        return 1
    fi
}

# Show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -t, --test-type TYPE    Test type: basic, stress, html (default: basic)"
    echo "  -h, --host HOST         Server host (default: localhost)"
    echo "  -p, --port PORT         Server port (default: 8000)"
    echo "  -u, --user-uuid UUID    User UUID (default: auto-generated)"
    echo "  -n, --num-messages N    Number of messages for stress test (default: 10)"
    echo "  --help                  Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Run basic test"
    echo "  $0 -t stress -n 50                   # Run stress test with 50 messages"
    echo "  $0 -t html                            # Open HTML test client"
    echo "  $0 -h 192.168.1.100 -p 8080          # Test remote server"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--test-type)
            TEST_TYPE="$2"
            shift 2
            ;;
        -h|--host)
            HOST="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -u|--user-uuid)
            USER_UUID="$2"
            shift 2
            ;;
        -n|--num-messages)
            NUM_MESSAGES="$2"
            shift 2
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    print_banner

    # Check server
    if ! check_server; then
        print_warning "Server is not running."
        print_info "Would you like to continue anyway? (html test only) [y/N]"

        # For non-interactive mode or if test type is not html, exit
        if [ "$TEST_TYPE" != "html" ]; then
            print_error "Server must be running for ${TEST_TYPE} test."
            print_info "Start server: cd /Users/thanhle/git/et/taas && uv run uvicorn eworksuite_api.main:app --reload --host 0.0.0.0 --port ${PORT}"
            exit 1
        fi

        print_warning "Continuing with HTML client (you'll need to start server separately)"
    fi

    # Handle test type
    case $TEST_TYPE in
        html)
            open_html_client
            ;;
        basic|stress)
            check_dependencies
            run_python_test
            ;;
        *)
            print_error "Unknown test type: $TEST_TYPE"
            print_info "Valid types: basic, stress, html"
            exit 1
            ;;
    esac

    echo ""
    print_success "Test completed!"
}

# Run main function
main
