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
    "api_mode": "chat_completions",
    "models": [{"id": model, "name": model}],
}
if api_key:
    provider["api_key"] = api_key
providers[provider_name] = provider

# Keep custom_providers in sync for older Hermes versions.
custom_providers = data.setdefault("custom_providers", [])
custom_providers[:] = [p for p in custom_providers if p.get("name") != provider_name]
custom_providers.append({
    "name": provider_name,
    "base_url": base_url,
    "api_mode": "chat_completions",
    "models": [{"id": model, "name": model}],
    **({"api_key": api_key} if api_key else {}),
})

if set_active:
    model_section = data.setdefault("model", {})
    model_section["provider"] = provider_name
    model_section["default"] = model
    # Remove stale global custom base_url/api_key that would override the provider.
    model_section.pop("base_url", None)
    model_section.pop("api_key", None)

with open(config_path, "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

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

# Restart Hermes gateway so it picks up the new custom provider.
read -rp "Restart Hermes gateway now? [Y/n]: " RESTART_ANSWER
RESTART_ANSWER="${RESTART_ANSWER:-Y}"
if [[ "$RESTART_ANSWER" =~ ^[Yy] ]]; then
    echo ""
    echo "Hermes gateway status BEFORE restart:"
    systemctl status hermes-gateway --no-pager || true

    echo ""
    echo "Restarting Hermes gateway ..."
    if systemctl restart hermes-gateway 2>/dev/null; then
        echo "Hermes gateway restarted."
    else
        echo "systemctl restart failed, trying 'hermes gateway restart' ..."
        hermes gateway restart || true
    fi

    echo ""
    echo "Hermes gateway status AFTER restart:"
    systemctl status hermes-gateway --no-pager || true
else
    echo "Skipped Hermes gateway restart. Remember to restart it manually:"
    echo "  systemctl restart hermes-gateway"
    echo "  # or"
    echo "  hermes gateway restart"
fi

echo ""
