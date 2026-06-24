#!/usr/bin/env bash
#
# Add the local Antigravity Bridge as a custom OpenAI-compatible provider in OpenClaw.
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
    echo ""
    echo "Available models (from bridge /v1/models):"
    echo "  Flash: gemini-2.5-flash, gemini-3-flash, gemini-3.1-flash-lite, ..."
    echo "  Pro:   gemini-3.1-pro-low, claude-sonnet-4-6, ..."
    echo "  Run: curl -s http://127.0.0.1:${PORT}/v1/models | jq '.data[].id'"
    echo ""
    DEFAULT_MODEL=$(ask_with_default "Model id" "gemini-2.5-flash")
fi

if [[ $# -ge 2 ]]; then
    PROVIDER_NAME="$2"
else
    PROVIDER_NAME=$(ask_with_default "Provider name" "antigravity-bridge")
fi

BASE_URL="http://127.0.0.1:${PORT}/v1"

CONFIG_DIR="${HOME}/.openclaw"
mkdir -p "$CONFIG_DIR"

CONFIG_PATH=""
for candidate in "${CONFIG_DIR}/openclaw.json" "${CONFIG_DIR}/config.json"; do
    if [[ -f "$candidate" ]]; then
        CONFIG_PATH="$candidate"
        break
    fi
done

if [[ -z "$CONFIG_PATH" ]]; then
    CONFIG_PATH="${CONFIG_DIR}/openclaw.json"
fi

echo "Configuring OpenClaw provider '${PROVIDER_NAME}' ..."
echo "  Config:   ${CONFIG_PATH}"
echo "  Base URL: ${BASE_URL}"
echo "  Model:    ${DEFAULT_MODEL}"

python3 - <<PY
import json
import os

path = os.path.expanduser("${CONFIG_PATH}")
provider_name = "${PROVIDER_NAME}"
base_url = "${BASE_URL}"
api_key = """${BRIDGE_API_KEY:-}""".strip()
model = "${DEFAULT_MODEL}"

data = {}
if os.path.exists(path):
    with open(path, "r") as f:
        data = json.load(f)

models = data.setdefault("models", {})
models.setdefault("mode", "merge")
providers = models.setdefault("providers", {})

provider = {
    "baseUrl": base_url,
    "api": "openai-completions",
    "models": [
        {
            "id": model,
            "name": model,
            "reasoning": False,
            "input": ["text"],
            "contextWindow": 128000,
            "maxTokens": 32000,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        }
    ],
}
if api_key:
    provider["apiKey"] = api_key
providers[provider_name] = provider

agents = data.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
agent_models = defaults.setdefault("models", {})
agent_models[f"{provider_name}/{model}"] = {"alias": model}

import time
backup = path + ".backup." + str(int(time.time()))
if os.path.exists(path):
    os.replace(path, backup)

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Updated", path)
PY

echo ""
echo "✔ OpenClaw provider '${PROVIDER_NAME}' is configured."
echo ""
echo "Then select the model in chat:"
echo "  /model ${DEFAULT_MODEL}"
echo ""

# Apply config and restart OpenClaw gateway so it picks up the new provider.
read -rp "Apply OpenClaw config and restart the gateway now? [Y/n]: " RESTART_ANSWER
RESTART_ANSWER="${RESTART_ANSWER:-Y}"
if [[ "$RESTART_ANSWER" =~ ^[Yy] ]]; then
    echo ""
    echo "Applying OpenClaw config ..."
    openclaw gateway config.apply --file "${CONFIG_PATH}" 2>/dev/null || true

    echo ""
    echo "Restarting OpenClaw gateway ..."
    if openclaw gateway restart 2>/dev/null; then
        echo "OpenClaw gateway restarted via openclaw CLI."
    elif systemctl restart openclaw-gateway 2>/dev/null; then
        echo "OpenClaw gateway restarted via systemctl."
    else
        echo "Could not restart OpenClaw gateway automatically."
        echo "Restart it manually, or apply the config with:"
        echo "  openclaw gateway config.apply --file ${CONFIG_PATH}"
    fi
else
    echo "Skipped OpenClaw gateway restart. Apply the config manually with:"
    echo "  openclaw gateway config.apply --file ${CONFIG_PATH}"
fi

echo ""
