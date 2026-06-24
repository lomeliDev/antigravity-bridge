#!/usr/bin/env bash
#
# Add the local Antigravity Bridge as a named custom OpenAI-compatible provider in Hermes.

#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ ! -f ".env" ]]; then
    echo "Error: .env not found. Run ./install.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
source .env

# Ensure the bridge has an API key. If .env does not have one, generate it
# automatically so clients like Hermes can authenticate.
if [[ -z "${BRIDGE_API_KEY:-}" ]]; then
    echo "No BRIDGE_API_KEY found in .env. Generating one ..."
    NEW_KEY=$(openssl rand -hex 24 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(24))")
    echo "BRIDGE_API_KEY=${NEW_KEY}" >> .env
    chmod 600 .env
    BRIDGE_API_KEY="${NEW_KEY}"
    echo "API key saved to .env. Restarting bridge service to pick it up ..."
    systemctl restart antigravity-bridge 2>/dev/null || \
    launchctl stop com.lomelidev.antigravity-bridge 2>/dev/null || \
    launchctl start com.lomelidev.antigravity-bridge 2>/dev/null || \
    true
    sleep 2
fi

# Ask with a default value. First argument is the prompt, second is the default.
ask_with_default() {
    local prompt="$1"
    local default_value="$2"
    local input
    read -rp "${prompt} [${default_value}]: " input
    echo "${input:-$default_value}"
}

# Use positional arguments if provided; otherwise ask interactively.
if [[ $# -ge 1 ]]; then
    DEFAULT_MODEL="$1"
else
    echo ""
    echo "Available models (from bridge /v1/models):"
    echo "  Flash:    gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash,"
    echo "            gemini-3.1-flash-lite, gemini-3.5-flash-extra-low, gemini-3.5-flash-low"
    echo "  Thinking: gemini-2.5-flash-thinking"
    echo "  Pro:      gemini-3.1-pro-low, gemini-pro-agent"
    echo "  Claude:   claude-sonnet-4-6, claude-opus-4-6-thinking"
    echo "  GPT:      gpt-oss-120b-medium"
    echo ""
    DEFAULT_MODEL=$(ask_with_default "Model id" "gemini-2.5-flash")
fi

if [[ $# -ge 2 ]]; then
    PROVIDER_NAME="$2"
else
    PROVIDER_NAME=$(ask_with_default "Provider name" "antigravity-bridge")
fi

BASE_URL="http://127.0.0.1:${PORT}/v1"

if ! command -v hermes >/dev/null 2>&1; then
    echo "Error: Hermes CLI was not found." >&2
    echo "Install Hermes first, then run this script again." >&2
    exit 1
fi

echo "Registering Antigravity Bridge as a Hermes provider ..."
echo "  Provider: ${PROVIDER_NAME}"
echo "  Base URL: ${BASE_URL}"
echo "  Model:    ${DEFAULT_MODEL}"

# Check for multiple Hermes profiles
PROFILE_DIR="${HOME}/.hermes"
if [[ -d "$PROFILE_DIR" ]]; then
    CONFIG_FILES=$(find "$PROFILE_DIR" -maxdepth 1 -name "config*.yaml" 2>/dev/null | wc -l)
    if [[ "$CONFIG_FILES" -gt 1 ]]; then
        echo "  ⚠ Multiple Hermes config files detected ($CONFIG_FILES)."
        echo "    This script edits ~/.hermes/config.yaml."
        echo "    Run again with HERMES_HOME to target other profiles."
        echo ""
    fi
fi

HERMES_CONFIG="${HERMES_HOME:-${HOME}/.hermes}/config.yaml"
mkdir -p "$(dirname "$HERMES_CONFIG")"

PYTHON_BIN="${REPO_DIR}/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Error: Python venv not found at ${REPO_DIR}/.venv" >&2
    exit 1
fi

# Ensure PyYAML is available in the venv for config editing.
if ! "$PYTHON_BIN" -c "import yaml" 2>/dev/null; then
    echo "Installing PyYAML into the bridge venv ..."
    "${REPO_DIR}/.venv/bin/pip" install -q pyyaml
fi

# Backup existing config if present.
if [[ -f "$HERMES_CONFIG" ]]; then
    cp "$HERMES_CONFIG" "${HERMES_CONFIG}.backup.$(date +%s)"
fi

read -rp "Set '${PROVIDER_NAME}' as the active Hermes provider? [Y/n]: " SET_ACTIVE
SET_ACTIVE="${SET_ACTIVE:-Y}"

"$PYTHON_BIN" - <<PY
import os
import yaml

config_path = os.path.expanduser("${HERMES_CONFIG}")
provider_name = "${PROVIDER_NAME}"
base_url = "${BASE_URL}"
api_key = """${BRIDGE_API_KEY:-}""".strip()
model = "${DEFAULT_MODEL}"
set_active = "${SET_ACTIVE}".lower().startswith("y")

if os.path.exists(config_path):
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
else:
    data = {}

# Hermes resolves named providers from the top-level 'providers' map.
providers = data.setdefault("providers", {})
provider = {
    "base_url": base_url,
    "models": [{"id": model, "name": model}],
}
if api_key:
    provider["api_key"] = api_key
providers[provider_name] = provider

# Drop custom_providers — not needed for Hermes ≥ 0.17.
# Keeping them can cause Hermes to treat the bridge as "custom"
# and fall back to OpenRouter.
data.pop("custom_providers", None)

model_section = data.setdefault("model", {})
old_provider = model_section.get("provider", "")
if set_active:
    model_section["provider"] = provider_name
    model_section["default"] = model

# Always remove stale global base_url/api_key/api_mode from model section.
# Hermes sometimes auto-fills OpenRouter's URL here when the provider
# name is 'custom' or the model is not found in the listing.
removed = []
for key in ("base_url", "api_key", "api_mode"):
    if key in model_section:
        del model_section[key]
        removed.append(key)
if removed:
    print(f"Removed stale model.{', '.join(removed)} — provider '{provider_name}' handles auth.")

with open(config_path, "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

# Verify the config took effect by re-reading it immediately.
final_provider = model_section.get("provider")
final_base_url = model_section.get("base_url", "")

if final_provider != provider_name and set_active:
    print(f"WARNING: model.provider is '{final_provider}', not '{provider_name}'.")
    print(f"         Hermes may have overwritten it. Run:")
    print(f"           hermes config set model.provider {provider_name}")
    print(f"           hermes config set model.default {model}")
elif old_provider and old_provider != provider_name and set_active:
    print(f"Provider changed: '{old_provider}' → '{provider_name}'")
if "openrouter" in str(final_base_url).lower():
    print(f"WARNING: model.base_url still points to OpenRouter ({final_base_url}).")
    print("         Remove it manually or the bridge will not be used.")

print(f"Updated {config_path}")
PY

echo ""
if [[ "${SET_ACTIVE}" =~ ^[Yy] ]]; then
    echo "✔ Hermes is configured to use '${PROVIDER_NAME}' as the active provider."
    echo "  Model: ${DEFAULT_MODEL}"
else
    echo "✔ Hermes now knows the provider '${PROVIDER_NAME}'."
    echo ""
    echo "To activate it manually, run:"
    echo "  /model ${PROVIDER_NAME}:${DEFAULT_MODEL}"
fi
echo ""

# ── Restart all Hermes components so they pick up the new provider ──
read -rp "Restart Hermes components now? [Y/n]: " RESTART_ANSWER
RESTART_ANSWER="${RESTART_ANSWER:-Y}"
if [[ "$RESTART_ANSWER" =~ ^[Yy] ]]; then
    echo ""
    echo "Restarting Hermes components ..."
    RESTART_ERRORS=0

    # 1) Gateway
    echo -n "  Gateway ... "
    if hermes gateway restart 2>/dev/null; then
        echo "✔ restarted"
    elif systemctl restart hermes-gateway 2>/dev/null; then
        echo "✔ restarted (systemctl)"
    elif [[ "$EUID" -eq 0 ]]; then
        pkill -f "hermes gateway" 2>/dev/null || true
        sleep 2
        nohup hermes gateway > /dev/null 2>&1 &
        echo "✔ restarted (direct)"
    else
        echo "⚠ skipped (not running or not found)"
        ((RESTART_ERRORS++)) || true
    fi

    # 2) Dashboard
    echo -n "  Dashboard ... "
    if hermes dashboard restart 2>/dev/null; then
        echo "✔ restarted"
    elif systemctl restart hermes-dashboard 2>/dev/null; then
        echo "✔ restarted (systemctl)"
    elif pkill -f "hermes dashboard" 2>/dev/null; then
        sleep 1
        nohup hermes dashboard --host 0.0.0.0 --port 9119 --no-open > /dev/null 2>&1 &
        echo "✔ restarted (direct)"
    else
        echo "⚠ skipped (not running or not found)"
        ((RESTART_ERRORS++)) || true
    fi

    # 3) WebUI (hermes-webui @ github.com/nesquena/hermes-webui)
    echo -n "  WebUI ... "
    if systemctl restart hermes-webui 2>/dev/null; then
        echo "✔ restarted (systemctl)"
    elif pkill -f "hermes-webui/server.py" 2>/dev/null; then
        sleep 1
        # Try to restart it — check common install paths
        if [[ -f /opt/hermes-webui/server.py ]]; then
            nohup /usr/local/lib/hermes-agent/venv/bin/python3 /opt/hermes-webui/server.py > /dev/null 2>&1 &
            echo "✔ restarted (direct)"
        elif command -v hermes-webui >/dev/null 2>&1; then
            nohup hermes-webui > /dev/null 2>&1 &
            echo "✔ restarted (CLI)"
        else
            echo "⚠ killed (restart manually: check hermes-webui install)"
            ((RESTART_ERRORS++)) || true
        fi
    else
        echo "⚠ skipped (not running or not found)"
        ((RESTART_ERRORS++)) || true
    fi

    # 4) Any remaining TUI sessions — notify the user, don't kill them
    TUI_COUNT=$(pgrep -f "tui_gateway" 2>/dev/null | wc -l)
    TUI_COUNT=$((TUI_COUNT + $(pgrep -f "ui-tui" 2>/dev/null | wc -l)))
    if [[ "$TUI_COUNT" -gt 0 ]]; then
        echo "  TUI      ... ⚠ $TUI_COUNT session(s) still running — close/reopen them to pick up the new provider"
    else
        echo "  TUI      ... ⚪ no active sessions"
    fi

    echo ""
    if [[ "$RESTART_ERRORS" -gt 0 ]]; then
        echo "⚠ $RESTART_ERRORS component(s) could not be restarted (may not be installed)."
        echo "  The provider config is saved — components will pick it up on next start."
    else
        echo "✔ All Hermes components restarted."
    fi
else
    echo "Skipped Hermes restart. Remember to restart manually:"
    echo "  hermes gateway restart"
    echo "  hermes dashboard restart"
    echo "  systemctl restart hermes-webui   # if installed"
fi

echo ""
