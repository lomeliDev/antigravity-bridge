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
# OpenCode / Antigravity prerequisite helpers
# ---------------------------------------------------------------------------
OPENCODE_CONFIG="${HOME}/.config/opencode/opencode.json"
ANTIGRAVITY_CLI_BIN="agy"

# Add the common install directories to PATH so we can find just-installed CLIs.
export PATH="${HOME}/.opencode/bin:${HOME}/.local/bin:${PATH}"

print_step() {
    local num="$1"
    local title="$2"
    echo ""
    echo -e "${CYAN}${BOLD}Step ${num}: ${title}${RESET}"
    echo "────────────────────────────────────────────────────────────────"
}

print_prereq_help() {
    echo ""
    echo -e "${BOLD}Manual prerequisite steps${RESET}"
    echo "────────────────────────────────────────────────────────────────"
    echo "The bridge reuses the Google OAuth session created by OpenCode."
    echo ""
    echo "1. Install the OpenCode CLI:"
    echo "     curl -fsSL https://opencode.ai/install | bash"
    echo ""
    echo "2. Install the Antigravity CLI:"
    echo "     curl -fsSL https://antigravity.google/cli/install.sh | bash"
    echo ""
    echo "3. Log in with the Antigravity CLI:"
    echo "     agy login"
    echo ""
    echo "4. Add the Antigravity auth plugin to ${OPENCODE_CONFIG}:"
    echo ""
    echo '     {'
    echo '       "plugin": ["opencode-antigravity-auth@latest"]'
    echo '     }'
    echo ""
    echo "5. Authenticate with Google through OpenCode:"
    echo "     opencode auth login"
    echo ""
    echo "   Select  Google  →  OAuth with Google (Antigravity)"
    echo "   and sign in with the same Google account."
    echo ""
    echo "6. Verify the credential was stored:"
    echo "     opencode auth list"
    echo ""
    echo "Then re-run this installer:"
    echo "     ./install.sh"
    echo ""
}

install_opencode() {
    warn "OpenCode CLI not found."
    read -rp "Install OpenCode automatically? [Y/n]: " INSTALL_OPENCODE
    INSTALL_OPENCODE="${INSTALL_OPENCODE:-Y}"
    if [[ ! "$INSTALL_OPENCODE" =~ ^[Yy]$ ]]; then
        print_prereq_help
        exit 1
    fi
    info "Installing OpenCode ..."
    curl -fsSL https://opencode.ai/install | bash
    export PATH="${HOME}/.opencode/bin:${HOME}/.local/bin:${PATH}"
    if ! command -v opencode >/dev/null 2>&1; then
        error "OpenCode was installed but is not on PATH in this shell."
        error "Run this command in a new terminal, then re-run the installer:"
        error "  export PATH=\"${HOME}/.opencode/bin:\${HOME}/.local/bin:\${PATH}\""
        exit 1
    fi
    success "OpenCode installed."
}

install_antigravity_cli() {
    warn "Antigravity CLI (agy) not found."
    read -rp "Install Antigravity CLI automatically? [Y/n]: " INSTALL_AGY
    INSTALL_AGY="${INSTALL_AGY:-Y}"
    if [[ ! "$INSTALL_AGY" =~ ^[Yy]$ ]]; then
        print_prereq_help
        exit 1
    fi
    info "Installing Antigravity CLI ..."
    curl -fsSL https://antigravity.google/cli/install.sh | bash
    export PATH="${HOME}/.local/bin:${PATH}"
    if ! command -v "$ANTIGRAVITY_CLI_BIN" >/dev/null 2>&1; then
        error "Antigravity CLI was installed but is not on PATH in this shell."
        error "Run this command in a new terminal, then re-run the installer:"
        error "  export PATH=\"${HOME}/.local/bin:\${PATH}\""
        exit 1
    fi
    success "Antigravity CLI installed."
}

install_opencode_plugin() {
    local config_path="$1"
    mkdir -p "$(dirname "$config_path")"
    if [[ -f "$config_path" ]]; then
        local backup_path="${config_path}.backup.$(date +%s)"
        cp "$config_path" "$backup_path"
        info "Created backup: ${backup_path}"
        python3 - <<PY
import json, sys
path = "${config_path}"
with open(path, "r") as f:
    data = json.load(f)
plugins = data.get("plugin", [])
if not isinstance(plugins, list):
    plugins = [plugins]
if not any("opencode-antigravity-auth" in p for p in plugins):
    plugins.append("opencode-antigravity-auth@latest")
    data["plugin"] = plugins
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Plugin added.")
else:
    print("Plugin already present.")
PY
    else
        cat > "$config_path" <<'EOF'
{
  "plugin": ["opencode-antigravity-auth@latest"]
}
EOF
        chmod 600 "$config_path"
        success "Created ${config_path} with the Antigravity auth plugin."
    fi
}

plugin_is_configured() {
    if [[ ! -f "$OPENCODE_CONFIG" ]]; then
        return 1
    fi
    python3 - <<PY
import json, sys
path = "${OPENCODE_CONFIG}"
try:
    with open(path, "r") as f:
        data = json.load(f)
    plugins = data.get("plugin", [])
    if not isinstance(plugins, list):
        plugins = [plugins]
    if any("opencode-antigravity-auth" in p for p in plugins):
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
}

agy_session_exists() {
    # Antigravity CLI stores OAuth state under ~/.gemini/antigravity-cli/.
    [[ -f "${HOME}/.gemini/antigravity-cli/credentials.enc" ]] || \
    [[ -f "${HOME}/.gemini/antigravity-cli/settings.json" ]]
}

opencode_google_auth_exists() {
    local auth_json="${HOME}/.local/share/opencode/auth.json"
    [[ -f "$auth_json" ]] || return 1
    python3 - <<PY
import json, sys
path = "${auth_json}"
try:
    with open(path, "r") as f:
        data = json.load(f)
    for key in ("google", "opencode-antigravity-auth"):
        entry = data.get(key)
        if isinstance(entry, dict) and entry.get("type") == "oauth":
            sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
}

run_interactive_login() {
    local tool="$1"
    local cmd="$2"
    echo ""
    warn "A browser tab will open so you can authenticate with Google."
    warn "Do NOT close this terminal until the login finishes and you return here."
    info "The installer will now run: ${cmd}"
    read -rp "Press Enter to open the login page ..."
    $cmd || true
}

check_opencode_prerequisites() {
    # Step 1: OpenCode CLI
    print_step 1 "Install OpenCode CLI"
    if ! command -v opencode >/dev/null 2>&1; then
        install_opencode
    else
        success "OpenCode CLI found: $(opencode --version 2>/dev/null | head -n1 || echo opencode)"
    fi

    # Step 2: Antigravity CLI (agy)
    print_step 2 "Install Antigravity CLI (agy)"
    if ! command -v "$ANTIGRAVITY_CLI_BIN" >/dev/null 2>&1; then
        install_antigravity_cli
    else
        success "Antigravity CLI found: $(${ANTIGRAVITY_CLI_BIN} --version 2>/dev/null | head -n1 || echo agy)"
    fi

    # Step 3: Antigravity CLI login
    print_step 3 "Log in with Antigravity CLI (agy)"
    if agy_session_exists; then
        success "An agy session was detected."
    else
        warn "No agy session was detected. The installer can run 'agy login' for you now."
        warn "If you skip this, the installer will exit and you can re-run it later."
        read -rp "Run 'agy login' now? [Y/n]: " RUN_AGY_LOGIN
        RUN_AGY_LOGIN="${RUN_AGY_LOGIN:-Y}"
        if [[ "$RUN_AGY_LOGIN" =~ ^[Yy]$ ]]; then
            # Try the newer 'agy login' subcommand; fall back to launching agy itself.
            if "$ANTIGRAVITY_CLI_BIN" login --help >/dev/null 2>&1; then
                run_interactive_login "agy" "$ANTIGRAVITY_CLI_BIN login"
            else
                run_interactive_login "agy" "$ANTIGRAVITY_CLI_BIN"
            fi
        fi
        if ! agy_session_exists; then
            warn "Still no agy session detected."
            read -rp "Did you complete the agy login successfully? [y/N]: " AGY_OK
            if [[ ! "${AGY_OK:-N}" =~ ^[Yy]$ ]]; then
                print_prereq_help
                exit 1
            fi
        fi
    fi
    success "Antigravity CLI login verified."

    # Step 4: opencode-antigravity-auth plugin
    print_step 4 "Configure opencode-antigravity-auth plugin"
    if plugin_is_configured; then
        success "opencode-antigravity-auth plugin is already configured."
    else
        warn "The opencode-antigravity-auth plugin is not configured."
        info "It is required so OpenCode can authenticate with Antigravity via Google OAuth."
        read -rp "Add the plugin automatically? [Y/n]: " INSTALL_PLUGIN
        INSTALL_PLUGIN="${INSTALL_PLUGIN:-Y}"
        if [[ "$INSTALL_PLUGIN" =~ ^[Yy]$ ]]; then
            install_opencode_plugin "$OPENCODE_CONFIG"
        else
            print_prereq_help
            exit 1
        fi
    fi

    # Step 5: OpenCode Google OAuth login
    print_step 5 "Log in with OpenCode (Google OAuth)"
    if opencode_google_auth_exists; then
        success "OpenCode Google OAuth credential found."
    else
        warn "No OpenCode Google OAuth credential found. The installer can run 'opencode auth login' for you now."
        warn "If you skip this, the installer will exit and you can re-run it later."
        read -rp "Run 'opencode auth login' now? [Y/n]: " RUN_OPENCODE_LOGIN
        RUN_OPENCODE_LOGIN="${RUN_OPENCODE_LOGIN:-Y}"
        if [[ "$RUN_OPENCODE_LOGIN" =~ ^[Yy]$ ]]; then
            run_interactive_login "opencode" "opencode auth login"
        fi
        if ! opencode_google_auth_exists; then
            warn "Still no OpenCode Google OAuth credential found."
            read -rp "Did you complete the OpenCode login successfully? [y/N]: " OPENCODE_OK
            if [[ ! "${OPENCODE_OK:-N}" =~ ^[Yy]$ ]]; then
                print_prereq_help
                exit 1
            fi
        fi
    fi
    success "OpenCode Google OAuth login verified."

    # Step 6: Credential file sanity check
    print_step 6 "Validate credential files"
    local cred_files_ok=true
    for path in "$DEFAULT_ANTIGRAVITY_CONST" "$DEFAULT_ANTIGRAVITY_ACCOUNTS" "$DEFAULT_ANTIGRAVITY_AUTH"; do
        if [[ -f "$path" ]]; then
            success "Found ${path}"
        else
            warn "Missing ${path}"
            cred_files_ok=false
        fi
    done
    if [[ "$cred_files_ok" == "false" ]]; then
        error "Some credential files are still missing."
        info "Try running: opencode auth list"
        info "If the login succeeded but files are missing, the plugin may use different paths."
        info "You can override paths with ANTIGRAVITY_CONST, ANTIGRAVITY_ACCOUNTS and ANTIGRAVITY_AUTH."
        read -rp "Continue anyway? [y/N]: " CONTINUE
        if [[ ! "${CONTINUE:-N}" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_PORT=52847
DEFAULT_ANTIGRAVITY_CONST="${ANTIGRAVITY_CONST:-$HOME/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js}"
DEFAULT_ANTIGRAVITY_ACCOUNTS="${ANTIGRAVITY_ACCOUNTS:-$HOME/.config/opencode/antigravity-accounts.json}"
DEFAULT_ANTIGRAVITY_AUTH="${ANTIGRAVITY_AUTH:-$HOME/.local/share/opencode/auth.json}"

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
# Main flow
# ---------------------------------------------------------------------------
print_header

if [[ "$EUID" -eq 0 ]]; then
    warn "You are running this installer as root."
    warn "The bridge and the service will be configured for the root user."
    read -rp "Continue as root? [y/N]: " CONTINUE_ROOT
    if [[ ! "${CONTINUE_ROOT:-N}" =~ ^[Yy]$ ]]; then
        info "Please run the installer as your normal user and try again."
        exit 0
    fi
fi

echo ""
echo -e "${BOLD}What this script will do${RESET}"
echo "────────────────────────────────────────────────────────────────"
echo "  1. Install OpenCode and the Antigravity CLI if they are missing."
echo "  2. Run the OAuth logins for you (browser tabs will open)."
echo "  3. Install the bridge and its Python dependencies."
echo "  4. Ask for a port and an optional API key."
echo "  5. Install and start a system service (systemd / launchd)."
echo ""
echo -e "${YELLOW}This is an unofficial tool. Use it at your own risk.${RESET}"
echo -e "${YELLOW}The author is not responsible for bans, rate limits or any other consequences.${RESET}"
echo ""
echo -e "${CYAN}Just press Enter to accept the defaults when prompted.${RESET}"
echo ""

# ---------------------------------------------------------------------------
# Python check (needed early for the prerequisite helpers)
# ---------------------------------------------------------------------------
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

check_opencode_prerequisites

info "Detected platform: ${DETECTED_OS} (${DETECTED_INIT})"

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
info "Credential files were already validated in the prerequisites step."

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
# Antigravity Bridge configuration
HOST=0.0.0.0
PORT=${PORT}
EOF

if [[ -n "$API_KEY" ]]; then
    echo "BRIDGE_API_KEY=${API_KEY}" >> .env
fi

cat >> .env <<EOF

# Credential sources
ANTIGRAVITY_CONST=${DEFAULT_ANTIGRAVITY_CONST}
ANTIGRAVITY_ACCOUNTS=${DEFAULT_ANTIGRAVITY_ACCOUNTS}
ANTIGRAVITY_AUTH=${DEFAULT_ANTIGRAVITY_AUTH}
EOF
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
    local curl_auth=()
    if [[ -n "$API_KEY" ]]; then
        curl_auth=(-H "Authorization: Bearer ${API_KEY}")
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
    health_status=$(curl -s -o /dev/null -w "%{http_code}" "${curl_auth[@]}" "$base_url/health" 2>/dev/null || true)
    if [[ "$health_status" == "200" ]]; then
        success "/health returned 200."
        curl -s "${curl_auth[@]}" "$base_url/health" | sed 's/^/     /'
    else
        error "/health returned ${health_status:-no response}."
        return 1
    fi

    info "Testing /v1/models ..."
    local models_status
    models_status=$(curl -s -o /dev/null -w "%{http_code}" "${curl_auth[@]}" "$base_url/v1/models" 2>/dev/null || true)
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

info "Check the logs:"
echo "     tail -f ${REPO_DIR}/bridge.log"

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

info "Test the bridge:"
echo "     curl -s http://127.0.0.1:${PORT}/health | jq"

echo ""
echo -e "${CYAN}Happy bridging!${RESET}"
