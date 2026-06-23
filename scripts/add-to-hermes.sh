#!/usr/bin/env bash
#
# Add the local Antigravity Bridge as a custom OpenAI-compatible provider in Hermes.
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
BASE_URL="http://127.0.0.1:${PORT}/v1"

if ! command -v hermes >/dev/null 2>&1; then
    echo "Error: Hermes CLI was not found." >&2
    echo "Install Hermes first, then run this script again." >&2
    exit 1
fi

echo "Configuring Hermes to use Antigravity Bridge ..."
echo "  Base URL: ${BASE_URL}"
echo "  Model:    ${DEFAULT_MODEL}"

# Hermes supports custom OpenAI-compatible endpoints through the model.* keys.
hermes config set model.provider custom
hermes config set model.base_url "$BASE_URL"
if [[ -n "${BRIDGE_API_KEY:-}" ]]; then
    hermes config set model.api_key "$BRIDGE_API_KEY"
fi
hermes config set model.default "$DEFAULT_MODEL"

echo ""
echo "✔ Hermes is now configured to use the Antigravity Bridge."
echo ""
echo "Start Hermes and switch models with:"
echo "  /model ${DEFAULT_MODEL}"
echo ""
