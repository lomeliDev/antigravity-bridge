#!/usr/bin/env bash
#
# Antigravity → OpenAI Bridge installer (standalone — no OpenCode required)
# Supports: Linux (systemd), macOS (launchd), and a portable fallback script.
#
# Based on the opencode-antigravity-auth plugin OAuth flow, but fully independent.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# ── Pretty output ──────────────────────────────────────────────
RESET='\033[0m'; BOLD='\033[1m'
CYAN='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${CYAN}${BOLD}  Antigravity Bridge installer (standalone)${RESET}"
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${RESET}"
    echo ""
}
info()    { echo -e "${CYAN}ℹ${RESET}  $*"; }
success() { echo -e "${GREEN}✔${RESET}  $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "${RED}✖${RESET}  $*"; }

# ── Defaults ───────────────────────────────────────────────────
DEFAULT_PORT=52847

# ── Platform detection ─────────────────────────────────────────
DETECTED_OS="unknown"; DETECTED_INIT="none"
if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "linux"* ]]; then
    DETECTED_OS="linux"
    command -v systemctl >/dev/null 2>&1 && DETECTED_INIT="systemd"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    DETECTED_OS="macos"
    command -v launchctl >/dev/null 2>&1 && DETECTED_INIT="launchd"
fi

# ── Main ───────────────────────────────────────────────────────
print_header

if [[ "$EUID" -eq 0 ]]; then
    warn "Running as root. The bridge will be configured for root."
    read -rp "Continue? [y/N]: " r
    [[ "${r:-N}" =~ ^[Yy]$ ]] || exit 0
fi

echo -e "${BOLD}What this script will do${RESET}"
echo "────────────────────────────────────────────────────────────────"
echo "  1. Install Python dependencies in a virtualenv."
echo "  2. Set up OAuth credentials (no OpenCode needed)."
echo "  3. Ask for a port and optional API key."
echo "  4. Install and start a system service (systemd / launchd)."
echo ""
echo -e "${YELLOW}Unofficial tool. Use at your own risk.${RESET}"
echo ""

# ── Python check ───────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    error "python3 not found. Install Python 3.10+."
    exit 1
fi
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    error "Python 3.10+ required. Found ${PY_MAJOR}.${PY_MINOR}."
    exit 1
fi
success "Python ${PY_MAJOR}.${PY_MINOR} ready."

# ── Virtualenv & deps ──────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    info "Creating .venv ..."
    python3 -m venv .venv
fi
info "Installing dependencies ..."
.venv/bin/pip install -q -r requirements.txt
success "Dependencies installed."

# ── OAuth setup (standalone — no OpenCode) ─────────────────────
echo ""
echo -e "${BOLD}Authentication${RESET}"
echo "────────────────────────────────────────────────────────────────"
echo ""
echo "The bridge needs a Google OAuth refresh_token for Gemini Code Assist."
echo "You have TWO options:"
echo ""
echo "  [1] I already have a refresh_token → paste it now"
echo "  [2] Log in interactively → the script will open a browser"
echo ""

BRIDGE_REFRESH_TOKEN=""
read -rp "Option [1/2]: " AUTH_MODE
AUTH_MODE="${AUTH_MODE:-2}"

if [[ "$AUTH_MODE" == "1" ]]; then
    read -rp "Paste your BRIDGE_REFRESH_TOKEN: " BRIDGE_REFRESH_TOKEN
    if [[ -z "$BRIDGE_REFRESH_TOKEN" ]]; then
        error "No token provided."
        exit 1
    fi
    success "Token accepted."
else
    info "Starting interactive OAuth login ..."
    info "A browser tab will open. Authorize, then paste the redirect URL."
    echo ""
    .venv/bin/python3 auth-login.py
    # auth-login.py saves the token to .env; read it back
    if [[ -f .env ]]; then
        BRIDGE_REFRESH_TOKEN=$(grep '^BRIDGE_REFRESH_TOKEN=' .env | cut -d= -f2-)
    fi
    if [[ -z "$BRIDGE_REFRESH_TOKEN" ]]; then
        error "Login did not produce a refresh_token. Check the output above."
        exit 1
    fi
    success "OAuth login complete."
fi

# ── Configuration ──────────────────────────────────────────────
echo ""
echo -e "${BOLD}Configuration${RESET}"
echo "────────────────────────────────────────────────────────────────"

read -rp "Listen port [${DEFAULT_PORT}]: " PORT
PORT="${PORT:-$DEFAULT_PORT}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 ]] || [[ "$PORT" -gt 65535 ]]; then
    error "Invalid port: ${PORT}"
    exit 1
fi

echo ""
echo "You can protect the bridge with API keys."
echo ""
echo "  [1] Single account — one BRIDGE_API_KEY for all clients (simple)"
echo "  [2] Multi-account — each Google account gets its own API key (advanced)"
echo ""
read -rp "Mode [1/2]: " ACCT_MODE
ACCT_MODE="${ACCT_MODE:-1}"

API_KEY=""
ADMIN_KEY=""
if [[ "$ACCT_MODE" == "2" ]]; then
    echo ""
    echo -e "${BOLD}Multi-account mode${RESET}"
    echo "────────────────────────────────────────────────────────────────"
    echo "Accounts are managed in accounts.json (see accounts.json.example)."
    echo "Add accounts later via: POST /admin/accounts"
    echo ""
    echo "Set an ADMIN key to protect the /admin/* endpoints."
    read -rp "Admin key (leave empty for open access): " ADMIN_KEY
    if [[ -n "$ADMIN_KEY" ]]; then
        success "Admin key set."
    else
        warn "No admin key — /admin/* endpoints are open."
    fi
    # Create empty accounts.json from the current token
    python3 -c "
import json
data = {'accounts': {}}
with open('accounts.json', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true
    chmod 600 accounts.json 2>/dev/null || true
    success "accounts.json created (add accounts via admin API)."
else
    echo ""
    echo "Clients must send: Authorization: Bearer <your-key>"
    read -rp "Require an API key? [Y/n]: " NEED_KEY
    NEED_KEY="${NEED_KEY:-Y}"

    if [[ "$NEED_KEY" =~ ^[Yy]$ ]]; then
        RANDOM_KEY="$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(24))')"
        read -rp "API key [random]: " API_KEY
        API_KEY="${API_KEY:-$RANDOM_KEY}"
        if [[ -z "$API_KEY" ]]; then
            error "API key cannot be empty."
            exit 1
        fi
        success "API key set."
    else
        info "No client authentication."
    fi
fi

mkdir -p auth_cache
chmod 700 auth_cache

# ── Write .env ─────────────────────────────────────────────────
cat > .env <<EOF
# Antigravity Bridge configuration
HOST=0.0.0.0
PORT=${PORT}
BRIDGE_REFRESH_TOKEN=${BRIDGE_REFRESH_TOKEN}
EOF

if [[ -n "$API_KEY" ]]; then
    echo "BRIDGE_API_KEY=${API_KEY}" >> .env
fi

chmod 600 .env
success "Configuration written to .env"

# ── Daemon files ───────────────────────────────────────────────
DAEMON_DIR="${REPO_DIR}/daemon"
mkdir -p "$DAEMON_DIR"
PYTHON_BIN_DIR="${REPO_DIR}/.venv/bin"

info "Generating daemon files ..."

# systemd service
sed -e "s|%USER%|$(whoami)|g" \
    -e "s|%HOME%|${HOME}|g" \
    -e "s|%WORK_DIR%|${REPO_DIR}|g" \
    -e "s|%PYTHON_BIN_DIR%|${PYTHON_BIN_DIR}|g" \
    -e "s|%PORT%|${PORT}|g" \
    "${REPO_DIR}/antigravity-bridge.service" > "${DAEMON_DIR}/antigravity-bridge.service"

# launchd plist
cat > "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
        <string>${PYTHON_BIN_DIR}:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>PORT</key>
        <string>${PORT}</string>
EOF
if [[ -n "$API_KEY" ]]; then
    echo "        <key>BRIDGE_API_KEY</key>" >> "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist"
    echo "        <string>${API_KEY}</string>" >> "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist"
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

# Portable runner
cat > "${DAEMON_DIR}/run.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${REPO_DIR}"
source .env
exec ${PYTHON_BIN_DIR}/python3 server.py --host 0.0.0.0 --port ${PORT}
EOF
chmod +x "${DAEMON_DIR}/run.sh"

success "Daemon files written to ${DAEMON_DIR}/"

# ── Install & start daemon ─────────────────────────────────────
echo ""
echo -e "${BOLD}Daemon installation${RESET}"
echo "────────────────────────────────────────────────────────────────"

install_systemd() {
    local unit="/etc/systemd/system/antigravity-bridge.service"
    info "Installing systemd service ..."
    if [[ "$EUID" -eq 0 ]]; then
        cp "${DAEMON_DIR}/antigravity-bridge.service" "$unit"
        systemctl daemon-reload
        systemctl enable antigravity-bridge
        systemctl restart antigravity-bridge
    elif command -v sudo >/dev/null 2>&1; then
        sudo cp "${DAEMON_DIR}/antigravity-bridge.service" "$unit"
        sudo systemctl daemon-reload
        sudo systemctl enable antigravity-bridge
        sudo systemctl restart antigravity-bridge
    else
        error "Root required for systemd. Run as root or install sudo."
        return 1
    fi
    success "systemd service installed."
}

install_launchd() {
    local plist_dir="$HOME/Library/LaunchAgents"
    local plist="${plist_dir}/com.lomelidev.antigravity-bridge.plist"
    mkdir -p "$plist_dir"
    info "Installing launchd agent ..."
    cp "${DAEMON_DIR}/com.lomelidev.antigravity-bridge.plist" "$plist"
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"
    success "launchd agent installed."
}

INSTALL_DAEMON="n"
if [[ "$DETECTED_INIT" == "systemd" ]]; then
    read -rp "Install systemd service? [Y/n]: " INSTALL_DAEMON
    INSTALL_DAEMON="${INSTALL_DAEMON:-Y}"
    [[ "$INSTALL_DAEMON" =~ ^[Yy]$ ]] && install_systemd
elif [[ "$DETECTED_INIT" == "launchd" ]]; then
    read -rp "Install launchd agent? [Y/n]: " INSTALL_DAEMON
    INSTALL_DAEMON="${INSTALL_DAEMON:-Y}"
    [[ "$INSTALL_DAEMON" =~ ^[Yy]$ ]] && install_launchd
else
    warn "No systemd/launchd detected. Use the portable runner:"
    info "  ${DAEMON_DIR}/run.sh"
fi

# ── Validation ─────────────────────────────────────────────────
run_tests() {
    local base_url="http://127.0.0.1:${PORT}"
    local curl_auth=()
    [[ -n "$API_KEY" ]] && curl_auth=(-H "Authorization: Bearer ${API_KEY}")

    echo ""
    echo -e "${BOLD}Validation${RESET}"
    echo "────────────────────────────────────────────────────────────────"

    info "Waiting for bridge ..."
    for _ in {1..15}; do
        curl -s -o /dev/null "$base_url/health" 2>/dev/null && break
        sleep 1
    done

    info "Testing /health ..."
    local s; s=$(curl -s -o /dev/null -w "%{http_code}" "${curl_auth[@]}" "$base_url/health" 2>/dev/null || true)
    [[ "$s" == "200" ]] && success "/health OK" || { error "/health returned ${s}"; return 1; }

    info "Testing /v1/models ..."
    local mc; mc=$(curl -s "${curl_auth[@]}" "$base_url/v1/models" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo 0)
    success "/v1/models: ${mc} models"

    info "Testing /v1/chat/completions ..."
    local cs; cs=$(curl -s -o /dev/null -w "%{http_code}" "${curl_auth[@]}" \
        -H "Content-Type: application/json" \
        -d '{"model":"gemini-2.5-flash","max_tokens":5,"messages":[{"role":"user","content":"say OK"}]}' \
        "$base_url/v1/chat/completions" 2>/dev/null || true)
    [[ "$cs" == "200" ]] && success "/v1/chat/completions OK" || warn "/v1/chat/completions returned ${cs}"

    echo ""
    success "All tests passed!"
}

if [[ "$INSTALL_DAEMON" =~ ^[Yy]$ ]]; then
    run_tests
else
    info "Skipping tests (daemon not started)."
    info "Start manually and test: curl http://127.0.0.1:${PORT}/health | jq"
fi

# ── Summary ────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo "────────────────────────────────────────────────────────────────"
info "Directory:  ${REPO_DIR}"
info "Port:       ${PORT}"
[[ -n "$API_KEY" ]] && info "API key:    ${API_KEY}" || info "API key:    (none)"
echo ""
info "Manage the service:"
if [[ "$DETECTED_INIT" == "systemd" ]]; then
    echo "  systemctl status antigravity-bridge"
    echo "  systemctl restart antigravity-bridge"
elif [[ "$DETECTED_INIT" == "launchd" ]]; then
    echo "  launchctl list com.lomelidev.antigravity-bridge"
else
    echo "  ${DAEMON_DIR}/run.sh"
fi
info "Test:"
echo "  curl http://127.0.0.1:${PORT}/v1/chat/completions \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\":\"gemini-2.5-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'"
echo ""

# ── Hermes integration (optional) ──────────────────────────────
if [[ -x "${REPO_DIR}/scripts/add-to-hermes.sh" ]]; then
    if command -v hermes >/dev/null 2>&1; then
        read -rp "Add to Hermes as a provider? [Y/n]: " r
        if [[ "${r:-Y}" =~ ^[Yy]$ ]]; then
            "${REPO_DIR}/scripts/add-to-hermes.sh" "${DEFAULT_MODEL:-gemini-2.5-flash}" "${PROVIDER_NAME:-antigravity-bridge}"
        fi
    fi
fi

echo -e "${CYAN}Happy bridging!${RESET}"
