#!/bin/bash

# LLM Research Proxy - Service Management Script
# Usage: ./manage.sh {start|stop|restart|status|logs|enable-rules|disable-rules|toggle-intercept}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/proxy.pid"
LOG_FILE="$SCRIPT_DIR/proxy.log"
PORT=8765
PYTHON_BIN="/home/XXBAi/.pyenv/versions/3.10.19/bin/python3"
UVICORN_BIN="/home/XXBAi/.pyenv/versions/3.10.19/bin/uvicorn"
API_BASE="http://localhost:$PORT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        pgrep -f "uvicorn app.main:app.*--port ${PORT}" | head -1
    fi
}

is_running() {
    local pid=$(get_pid)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_service() {
    if is_running; then
        print_warning "Service is already running (PID: $(get_pid))"
        return 0
    fi

    cd "$SCRIPT_DIR"
    print_status "Starting LLM Research Proxy on port $PORT..."

    # Check if clash proxy is available
    if curl -s -o /dev/null -w "" -x http://127.0.0.1:7890 --connect-timeout 2 https://openrouter.ai 2>/dev/null; then
        print_success "Clash proxy detected, using proxy for upstream requests"
        nohup env HTTP_PROXY="http://127.0.0.1:7890" HTTPS_PROXY="http://127.0.0.1:7890" \
            "$UVICORN_BIN" app.main:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
    else
        print_warning "Clash proxy not detected, running without proxy"
        nohup "$UVICORN_BIN" app.main:app --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
    fi

    local pid=$!
    echo "$pid" > "$PID_FILE"

    # Wait for service to start
    sleep 3

    if is_running; then
        print_success "Service started successfully (PID: $(get_pid))"
        print_status "API Endpoint: http://localhost:$PORT"
        print_status "Intercept UI: http://localhost:$PORT/intercept/ui"
        print_status "Health Check: http://localhost:$PORT/health"
        return 0
    else
        print_error "Failed to start service. Check logs: $LOG_FILE"
        return 1
    fi
}

stop_service() {
    if ! is_running; then
        print_warning "Service is not running"
        return 0
    fi

    local pid=$(get_pid)
    print_status "Stopping service (PID: $pid)..."

    kill "$pid" 2>/dev/null
    sleep 2

    # Force kill if still running
    if is_running; then
        print_warning "Force stopping..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi

    rm -f "$PID_FILE"
    print_success "Service stopped"
    return 0
}

restart_service() {
    stop_service
    sleep 1
    start_service
}

show_status() {
    echo ""
    echo "┌─────────────────────────────────────────────────┐"
    echo "│     LLM Research Proxy - Service Status         │"
    echo "├─────────────────────────────────────────────────┤"

    if is_running; then
        echo -e "│ Status:  ${GREEN}Running${NC}                              │"
        echo -e "│ PID:     $(get_pid)                                       │"
        echo -e "│ Port:    $PORT                                          │"
        echo -e "│ API:     http://localhost:$PORT                           │"
        echo -e "│ UI:      http://localhost:$PORT/intercept/ui              │"
    else
        echo -e "│ Status:  ${RED}Stopped${NC}                                │"
    fi

    echo "├─────────────────────────────────────────────────┤"
    echo "│ Quick Commands:                                 │"
    echo "│   ./manage.sh start   - Start service           │"
    echo "│   ./manage.sh stop    - Stop service            │"
    echo "│   ./manage.sh restart - Restart service         │"
    echo "│   ./manage.sh logs    - View logs               │"
    echo "└─────────────────────────────────────────────────┘"
    echo ""
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -50 "$LOG_FILE"
    else
        print_warning "No log file found"
    fi
}

enable_rules() {
    print_status "Enabling force model rule..."
    local response=$(curl -s "$API_BASE/rules/toggle-model-force?enable=true")
    if echo "$response" | grep -q '"success":true' || echo "$response" | grep -q '"success": true'; then
        print_success "Force model rule enabled"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    else
        print_error "Failed to enable rule"
        echo "$response"
    fi
}

disable_rules() {
    print_status "Disabling force model rule..."
    local response=$(curl -s "$API_BASE/rules/toggle-model-force?enable=false")
    if echo "$response" | grep -q '"success":true' || echo "$response" | grep -q '"success": true'; then
        print_success "Force model rule disabled"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    else
        print_error "Failed to disable rule"
        echo "$response"
    fi
}

enable_intercept() {
    print_status "Enabling intercept mode..."
    local response=$(curl -s -X POST "$API_BASE/intercept/mode/enable")
    if echo "$response" | grep -q '"success": true'; then
        print_success "Intercept mode enabled"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    else
        print_error "Failed to enable intercept mode"
        echo "$response"
    fi
}

disable_intercept() {
    print_status "Disabling intercept mode..."
    local response=$(curl -s -X POST "$API_BASE/intercept/mode/disable")
    if echo "$response" | grep -q '"success": true'; then
        print_success "Intercept mode disabled"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    else
        print_error "Failed to disable intercept mode"
        echo "$response"
    fi
}

show_quick_status() {
    echo ""
    echo "┌─────────────────────────────────────────────────┐"
    echo "│     LLM Research Proxy - Quick Status           │"
    echo "├─────────────────────────────────────────────────┤"

    # Service status
    if is_running; then
        echo -e "│ Service:  ${GREEN}Running${NC} (PID: $(get_pid))               │"
    else
        echo -e "│ Service:  ${RED}Stopped${NC}                                  │"
    fi

    # Intercept mode status
    local intercept_status=$(curl -s "$API_BASE/intercept/mode" 2>/dev/null)
    local intercept_enabled=$(echo "$intercept_status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('enabled', False))" 2>/dev/null || echo "unknown")
    if [ "$intercept_enabled" = "True" ]; then
        echo -e "│ Intercept: ${YELLOW}Enabled${NC}                                  │"
    elif [ "$intercept_enabled" = "False" ]; then
        echo -e "│ Intercept: ${GREEN}Disabled${NC}                                  │"
    else
        echo -e "│ Intercept: ${RED}Unknown (service may not be running)${NC}   │"
    fi

    # Rule status
    echo "│                                               │"
    echo "│ Rules: Edit rules/request.yaml manually       │"
    echo "│   or use: ./manage.sh disable-rules           │"
    echo "├─────────────────────────────────────────────────┤"
    echo "│ Quick Commands:                                 │"
    echo "│   ./manage.sh start         - Start service     │"
    echo "│   ./manage.sh stop          - Stop service      │"
    echo "│   ./manage.sh restart       - Restart service   │"
    echo "│   ./manage.sh enable-rules  - Enable model rule │"
    echo "│   ./manage.sh disable-rules - Disable model rule│"
    echo "│   ./manage.sh logs          - View logs         │"
    echo "└─────────────────────────────────────────────────┘"
    echo ""
}

# Main command handler
case "${1:-status}" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_quick_status
        ;;
    logs)
        show_logs
        ;;
    enable-rules)
        enable_rules
        ;;
    disable-rules)
        disable_rules
        ;;
    enable-intercept)
        enable_intercept
        ;;
    disable-intercept)
        disable_intercept
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|enable-rules|disable-rules|enable-intercept|disable-intercept}"
        echo ""
        echo "Commands:"
        echo "  start             - Start the proxy service"
        echo "  stop              - Stop the proxy service"
        echo "  restart           - Restart the proxy service"
        echo "  status            - Show service status"
        echo "  logs              - Show recent logs"
        echo "  enable-rules      - Enable force model rule"
        echo "  disable-rules     - Disable force model rule"
        echo "  enable-intercept  - Enable intercept mode"
        echo "  disable-intercept - Disable intercept mode"
        exit 1
        ;;
esac

exit $?
