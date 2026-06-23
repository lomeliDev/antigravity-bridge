#!/usr/bin/env bash
#
# Antigravity → OpenAI Bridge installer
# Supports: Linux (systemd), macOS (launchd), and a portable fallback script.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# ---------------------------------------------------------------------------
# Pretty output helpers
# ---------------------------------------------------------------------------
RESET='\033[0m'
BOLD='\033[1m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${CYAN}${BOLD}  Antigravity Bridge installer${RESET}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${RESET}"
    echo ""
}

info()    { echo -e "${CYAN}ℹ${RESET}  $*"; }
success() { echo -e "${GREEN}✔${RESET}  $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "${RED}✖${RESET}  $*"; }

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PORT=8080
DEFAULT_ANTIGRAVITY_CONST="${ANTIGRAVITY_CONST:-$HOME/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js}"
DEFAULT_ANTIGRAVITY_ACCOUNTS="${ANTIGRAVITY_ACCOUNTS:-$HOME/.config/opencode/antigravity-accounts.json}"
DEFAULT_ANTIGRAVITY_AUTH="${ANTIGRAVITY_AUTH:-$HOME/.local/share/opencode/auth.json}"

CREDENTIALS_OK=true

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
DETECTED_OS="unknown"
DETECTED_INIT="none"

if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "linux"* ]]; then
    DETECTED_OS="linux"
    if command -v systemctl >/dev/null 2>&1; then
        DETECTED_INIT="systemd"
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    DETECTED_OS="macos"
    if command -v launchctl >/dev/null 2>&1; then
        DETECTED_INIT="launchd"
    fi
fi

# ---------------------------------------------------------------------------
# Python check
# ---------------------------------------------------------------------------
print_header

info "Detected platform: ${DETECTED_OS} (${DETECTED_INIT})"

if ! command -v python3 >/dev/null 2>&1; then
    error "python3 was not found. Please install Python 3.10 or newer and try again."
    exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    error "Python 3.10+ is required. Found ${PY_MAJOR}.${PY_MINOR}."
    exit 1
fi
success "Python ${PY_MAJOR}.${PY_MINOR} is ready."

# ---------------------------------------------------------------------------
# Virtual environment & dependencies
# ---------------------------------------------------------------------------
if [[ ! -d ".venv" ]]; then
    info "Creating Python virtual environment in .venv ..."
    python3 -m venv .venv
fi

info "Installing Python dependencies ..."
.venv/bin/pip install -q -r requirements.txt
success "Dependencies installed."

# ---------------------------------------------------------------------------
# Antigravity / OpenCode credential validation
# ---------------------------------------------------------------------------
info "Looking for Antigravity credentials ..."

CRED_LABELS=("constants.js" "accounts.json" "auth.json")
CRED_PATHS=("$DEFAULT_ANTIGRAVITY_CONST" "$DEFAULT_ANTIGRAVITY_ACCOUNTS" "$DEFAULT_ANTIGRAVITY_AUTH")
for i in "${!CRED_LABELS[@]}"; do
    label="${CRED_LABELS[$i]}"
    path="${CRED_PATHS[$i]}"
    if [[ -f "$path" ]]; then
        success "Found ${label}: ${path}"
    else
        warn "Missing ${label}: ${path}"
        CREDENTIALS_OK=false
    fi
done

if [[ "$CREDENTIALS_OK" == "false" ]]; then
    warn "One or more Antigravity credential files were not found."
    warn "The bridge needs these files to authenticate with Antigravity."
    read -rp "Continue anyway? [y/N]: " CONTINUE
    if [[ ! "${CONTINUE:-N}" =~ ^[Yy]$ ]]; then
        info "Installation cancelled."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Configuration prompts
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}Configuration${RESET}"
echo "────────────────────────────────────────────────────────────────"

read -rp "Listen port [${DEFAULT_PORT}]: " PORT
PORT="${PORT:-$DEFAULT_PORT}"

# Validate port
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 ]] || [[ "$PORT" -gt 65535 ]]; then
    error "Invalid port: ${PORT}. Please enter a number between 1 and 65535."
    exit 1
fi

# API key prompt
RANDOM_KEY="$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(24))')"

echo ""
echo "You can protect the bridge with an API key."
echo "Clients must send: Authorization: Bearer <key>"
read -rp "Require an API key? [Y/n]: " NEED_KEY
NEED_KEY="${NEED_KEY:-Y}"

API_KEY=""
if [[ "$NEED_KEY" =~ ^[Yy]$ ]]; then
    read -rp "Bridge API key [random]: " API_KEY
    API_KEY="${API_KEY:-$RANDOM_KEY}"
    if [[ -z "$API_KEY" ]]; then
        error "API key cannot be empty when authentication is enabled."
        exit 1
    fi
    success "API key set."
else
    info "Running without client API key authentication."
fi

# ---------------------------------------------------------------------------
# Write .env
# ---------------------------------------------------------------------------
cat > .env <<EOF
PORT=${PORT}
EOF

if [[ -n "$API_KEY" ]]; then
    echo "BRIDGE_API_KEY=${API_KEY}" >> .env
fi
chmod 600 .env
success "Wrote configuration to .env"

# ---------------------------------------------------------------------------
# Daemon configuration generators
# ---------------------------------------------------------------------------
DAEMON_DIR="${REPO_DIR}/daemon"
mkdir -p "$DAEMON_DIR"

PYTHON_BIN_DIR="${REPO_DIR}/.venv/bin"

info "Generating daemon files ..."

# systemd service
sed -e "s|%USER%|$(whoami)|g" \
    -e "s|%WORK_DIR%|${REPO_DIR}|g" \
    -e "s|%PYTHON_BIN_DIR%|${PYTHON_BIN_DIR}|g" \
    -e "s|%PORT%|${PORT}|g" \
    -e "s|%BRIDGE_API_KEY%|${API_KEY}|g" \
    -e "s|%ANTIGRAVITY_CONST%|${DEFAULT_ANTIGRAVITY_CONST}|g" \
    -e "s|%ANTIGRAVITY_ACCOUNTS%|${DEFAULT_ANTIGRAVITY_ACCOUNTS}|g" \
    -e "s|%ANTIGRAVITY_AUTH%|${DEFAULT_ANTIGRAVITY_AUTH}|g" \
    "${REPO_DIR}/antigravity-bridge.service" > "${DAEMON_DIR}/antigravity-bridge.service"

# launchd plist
cat > "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lomelidev.antigravity-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN_DIR}/python3</string>
        <string>${REPO_DIR}/server.py</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PYTHON_BIN_DIR}:/usr/local/bin:/usr/bin:/bin</string>
        <key>PORT</key>
        <string>${PORT}</string>
        <key>ANTIGRAVITY_CONST</key>
        <string>${DEFAULT_ANTIGRAVITY_CONST}</string>
        <key>ANTIGRAVITY_ACCOUNTS</key>
        <string>${DEFAULT_ANTIGRAVITY_ACCOUNTS}</string>
        <key>ANTIGRAVITY_AUTH</key>
        <string>${DEFAULT_ANTIGRAVITY_AUTH}</string>
EOF

if [[ -n "$API_KEY" ]]; then
    cat >> "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" <<EOF
        <key>BRIDGE_API_KEY</key>
        <string>${API_KEY}</string>
EOF
fi

cat >> "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" <<EOF
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${REPO_DIR}/bridge.log</string>
    <key>StandardErrorPath</key>
    <string>${REPO_DIR}/bridge.log</string>
</dict>
</plist>
EOF

# Portable fallback run script
cat > "${DAEMON_DIR}/run.sh" <<EOF
#!/usr/bin/env bash
# Manual runner used when systemd/launchd are not available.
set -euo pipefail
cd "${REPO_DIR}"
source .env
exec ${PYTHON_BIN_DIR}/python3 server.py --host 0.0.0.0 --port ${PORT}
EOF
chmod +x "${DAEMON_DIR}/run.sh"

success "Daemon files written to ${DAEMON_DIR}/"

# ---------------------------------------------------------------------------
# Install & start daemon
# ---------------------------------------------------------------------------
install_systemd() {
    local unit="/etc/systemd/system/antigravity-bridge.service"
    info "Installing systemd service ..."
    if [[ "$EUID" -eq 0 ]]; then
        cp "${DAEMON_DIR}/antigravity-bridge.service" "$unit"
        systemctl daemon-reload
        systemctl enable --now antigravity-bridge
    elif command -v sudo >/dev/null 2>&1; then
        sudo cp "${DAEMON_DIR}/antigravity-bridge.service" "$unit"
        sudo systemctl daemon-reload
        sudo systemctl enable --now antigravity-bridge
    else
        error "Root privileges are required to install the systemd service."
        return 1
    fi
    success "systemd service installed and started."
}

install_launchd() {
    local plist_dir="$HOME/Library/LaunchAgents"
    local plist="${plist_dir}/com.lomelidev.antigravity-bridge.plist"
    mkdir -p "$plist_dir"
    info "Installing launchd agent ..."
    cp "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" "$plist"
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"
    success "launchd agent installed and started."
}

echo ""
echo -e "${BOLD}Daemon installation${RESET}"
echo "────────────────────────────────────────────────────────────────"

if [[ "$DETECTED_INIT" == "systemd" ]]; then
    read -rp "Install and start the systemd service? [Y/n]: " INSTALL_DAEMON
    INSTALL_DAEMON="${INSTALL_DAEMON:-Y}"
    if [[ "$INSTALL_DAEMON" =~ ^[Yy]$ ]]; then
        install_systemd || exit 1
    else
        info "Skipped systemd install. Service file is available at:"
        info "  ${DAEMON_DIR}/antigravity-bridge.service"
    fi
elif [[ "$DETECTED_INIT" == "launchd" ]]; then
    read -rp "Install and start the launchd agent? [Y/n]: " INSTALL_DAEMON
    INSTALL_DAEMON="${INSTALL_DAEMON:-Y}"
    if [[ "$INSTALL_DAEMON" =~ ^[Yy]$ ]]; then
        install_launchd || exit 1
    else
        info "Skipped launchd install. Plist is available at:"
        info "  ${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist"
    fi
else
    warn "No supported service manager found (systemd or launchd)."
    info "Use the portable runner:"
    info "  ${DAEMON_DIR}/run.sh"
    INSTALL_DAEMON="n"
fi

# ---------------------------------------------------------------------------
# Final validation tests
# ---------------------------------------------------------------------------
run_tests() {
    local base_url="http://127.0.0.1:${PORT}"
    local auth_header=""
    if [[ -n "$API_KEY" ]]; then
        auth_header="-H Authorization: Bearer ${API_KEY}"
    fi

    echo ""
    echo -e "${BOLD}Validation tests${RESET}"
    echo "────────────────────────────────────────────────────────────────"

    info "Waiting for the bridge to start ..."
    for _ in {1..12}; do
        if curl -s -o /dev/null -w "%{http_code}" "$base_url/health" 2>/dev/null | grep -q '^200$'; then
            break
        fi
        sleep 1
    done

    info "Testing /health ..."
    local health_status
    health_status=$(curl -s -o /dev/null -w "%{http_code}" $auth_header "$base_url/health" 2>/dev/null || true)
    if [[ "$health_status" == "200" ]]; then
        success "/health returned 200."
        curl -s $auth_header "$base_url/health" | sed 's/^/     /'
    else
        error "/health returned ${health_status:-no response}."
        return 1
    fi

    info "Testing /v1/models ..."
    local models_status
    models_status=$(curl -s -o /dev/null -w "%{http_code}" $auth_header "$base_url/v1/models" 2>/dev/null || true)
    if [[ "$models_status" == "200" ]]; then
        success "/v1/models returned 200."
    else
        error "/v1/models returned ${models_status:-no response}."
        return 1
    fi

    echo ""
    success "All validation tests passed!"
    return 0
}

if [[ "${INSTALL_DAEMON:-Y}" =~ ^[Yy]$ ]]; then
    run_tests
else
    info "Skipping validation tests because the daemon was not started."
    info "After starting the bridge, test it with:"
    info "  curl -s http://127.0.0.1:${PORT}/health | jq"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo "────────────────────────────────────────────────────────────────"
info "Working directory: ${REPO_DIR}"
info "Listen port:       ${PORT}"
if [[ -n "$API_KEY" ]]; then
    info "API key:           ${API_KEY}"
else
    info "API key:           (none / no client auth)"
fi

if [[ "$DETECTED_INIT" == "systemd" ]]; then
    info "Manage the service:"
    echo "     sudo systemctl status antigravity-bridge"
    echo "     sudo systemctl restart antigravity-bridge"
    echo "     sudo systemctl stop antigravity-bridge"
elif [[ "$DETECTED_INIT" == "launchd" ]]; then
    info "Manage the agent:"
    echo "     launchctl list com.lomelidev.antigravity-bridge"
    echo "     launchctl stop com.lomelidev.antigravity-bridge"
    echo "     launchctl start com.lomelidev.antigravity-bridge"
else
    info "Start manually:"
    echo "     ${DAEMON_DIR}/run.sh"
fi

echo ""
echo -e "${CYAN}Happy bridging!${RESET}"
