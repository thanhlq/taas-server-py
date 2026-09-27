#!/bin/bash
# Complete WebSocket Test Suite Runner
# This script checks everything and guides you through testing

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="/Users/thanhle/git/et/taas"

print_header() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║         WebSocket Testing Suite - Complete Check          ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${CYAN}▶${NC} $1"
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

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check 1: Dependencies
check_dependencies() {
    print_step "Checking dependencies..."

    local all_ok=true

    # Check uv
    if command -v uv &> /dev/null; then
        print_success "uv is installed"
    else
        print_error "uv is not installed"
        print_info "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        all_ok=false
    fi

    # Check python-socketio
    if uv run python -c "import socketio" 2>/dev/null; then
        print_success "python-socketio is installed"
    else
        print_warning "python-socketio is not installed"
        print_info "Installing now..."
        uv pip install 'python-socketio[client]' aiohttp
        if [ $? -eq 0 ]; then
            print_success "python-socketio installed successfully"
        else
            print_error "Failed to install python-socketio"
            all_ok=false
        fi
    fi

    # Check aiohttp
    if uv run python -c "import aiohttp" 2>/dev/null; then
        print_success "aiohttp is installed"
    else
        print_warning "aiohttp is not installed (should be installed with socketio)"
    fi

    echo ""
    return 0
}

# Check 2: Files
check_files() {
    print_step "Checking test files..."

    local files=(
        "test_websocket.py"
        "test_websocket.html"
        "run_websocket_test.sh"
        "start_server.sh"
    )

    for file in "${files[@]}"; do
        if [ -f "${SCRIPT_DIR}/${file}" ]; then
            print_success "${file}"
        else
            print_error "${file} not found"
        fi
    done

    echo ""
}

# Check 3: Server
check_server() {
    print_step "Checking if server is running..."

    if curl -s "http://localhost:8000/docs" > /dev/null 2>&1; then
        print_success "Server is running on port 8000"
        echo ""
        return 0
    else
        print_warning "Server is not running"
        echo ""
        return 1
    fi
}

# Show test options
show_options() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Available Test Options${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "1) Start the server"
    echo "2) Run basic WebSocket test"
    echo "3) Run stress test"
    echo "4) Open HTML test client"
    echo "5) Run all automated tests"
    echo "6) Exit"
    echo ""
}

# Start server
start_server() {
    print_info "Starting server..."
    echo ""

    if [ -f "${SCRIPT_DIR}/start_server.sh" ]; then
        "${SCRIPT_DIR}/start_server.sh"
    else
        cd "$PROJECT_ROOT"
        uv run uvicorn ews_api.main:app --reload --host 0.0.0.0 --port 8000
    fi
}

# Run basic test
run_basic_test() {
    print_info "Running basic WebSocket test..."
    echo ""

    cd "$SCRIPT_DIR"
    uv run python test_websocket.py --test-type basic
}

# Run stress test
run_stress_test() {
    print_info "Running stress test with 50 messages..."
    echo ""

    cd "$SCRIPT_DIR"
    uv run python test_websocket.py --test-type stress --num-messages 50
}

# Open HTML client
open_html_client() {
    print_info "Opening HTML test client..."

    if [ -f "${SCRIPT_DIR}/test_websocket.html" ]; then
        open "${SCRIPT_DIR}/test_websocket.html"
        print_success "HTML client opened in browser"
    else
        print_error "test_websocket.html not found"
    fi
}

# Run all tests
run_all_tests() {
    print_info "Running all automated tests..."
    echo ""

    echo -e "${CYAN}Test 1: Basic Connection${NC}"
    cd "$SCRIPT_DIR"
    uv run python test_websocket.py --test-type basic --user-uuid test-user-1

    echo ""
    echo -e "${CYAN}Test 2: Stress Test${NC}"
    uv run python test_websocket.py --test-type stress --num-messages 20 --user-uuid test-user-2

    echo ""
    print_success "All tests completed!"
}

# Main menu
main() {
    print_header

    # Run checks
    check_dependencies
    check_files

    # Check if server is running
    if ! check_server; then
        print_warning "Server needs to be running for tests to work"
        print_info "You can start it with option 1"
        echo ""
    fi

    # Interactive menu
    while true; do
        show_options
        read -p "Select an option (1-6): " choice
        echo ""

        case $choice in
            1)
                start_server
                break
                ;;
            2)
                if ! check_server; then
                    print_error "Server is not running. Please start it first (option 1)"
                    echo ""
                else
                    run_basic_test
                    echo ""
                    read -p "Press Enter to continue..."
                fi
                ;;
            3)
                if ! check_server; then
                    print_error "Server is not running. Please start it first (option 1)"
                    echo ""
                else
                    run_stress_test
                    echo ""
                    read -p "Press Enter to continue..."
                fi
                ;;
            4)
                open_html_client
                echo ""
                read -p "Press Enter to continue..."
                ;;
            5)
                if ! check_server; then
                    print_error "Server is not running. Please start it first (option 1)"
                    echo ""
                else
                    run_all_tests
                    echo ""
                    read -p "Press Enter to continue..."
                fi
                ;;
            6)
                print_info "Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid option. Please select 1-6"
                echo ""
                ;;
        esac
    done
}

# Run main
main
