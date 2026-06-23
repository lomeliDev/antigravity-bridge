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

DEFAULT_MODEL="${1:-gemini-2.5-flash}"
PROVIDER_NAME="${2:-antigravity-bridge}"
BASE_URL="http://127.0.0.1:${PORT}/v1"

if ! command -v hermes >/dev/null 2>&1; then
    echo "Error: Hermes CLI was not found." >&2
    echo "Install Hermes first, then run this script again." >&2
    exit 1
fi

echo "Configuring Hermes to use Antigravity Bridge ..."
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

"$PYTHON_BIN" - <<PY
import os
import yaml

config_path = os.path.expanduser("${HERMES_CONFIG}")
provider_name = "${PROVIDER_NAME}"
base_url = "${BASE_URL}"
api_key = """${BRIDGE_API_KEY:-}""".strip()
model = "${DEFAULT_MODEL}"

if os.path.exists(config_path):
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
else:
    data = {}

# Ensure custom_providers list exists and remove any previous entry with same name.
custom_providers = data.setdefault("custom_providers", [])
custom_providers[:] = [p for p in custom_providers if p.get("name") != provider_name]

provider = {
    "name": provider_name,
    "base_url": base_url,
    "api_mode": "chat_completions",
    "models": [{"id": model, "name": model}],
}
if api_key:
    provider["api_key"] = api_key

custom_providers.append(provider)

# Set active model to the named custom provider.
# Remove any stale top-level base_url/api_key that may be left over from a
# previous provider, because Hermes ignores them when using custom:<name>.
model_section = data.setdefault("model", {})
model_section["provider"] = f"custom:{provider_name}"
model_section["default"] = model
model_section.pop("base_url", None)
model_section.pop("api_key", None)

with open(config_path, "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

print(f"Updated {config_path}")
PY

echo ""
echo "✔ Hermes is now configured with provider 'custom:${PROVIDER_NAME}'."
echo ""
echo "Restart Hermes so it reads the new config:"
echo "  hermes gateway restart     # if you use the gateway"
echo "  # or close and reopen Hermes if you use the CLI/TUI"
echo ""
echo "Then switch models with:"
echo "  /model custom:${PROVIDER_NAME}:${DEFAULT_MODEL}"
echo ""
