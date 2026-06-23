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

DEFAULT_MODEL="${1:-gemini-2.5-flash}"
PROVIDER_NAME="${2:-antigravity-bridge}"
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
echo "Apply the config and restart the gateway:"
echo "  openclaw gateway config.apply --file ${CONFIG_PATH}"
echo ""
echo "Then select the model in chat:"
echo "  /model ${DEFAULT_MODEL}"
echo ""
