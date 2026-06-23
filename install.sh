#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "============================================================"
echo "  Antigravity -> OpenAI Bridge installer"
echo "============================================================"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Please install Python 3.10 or newer."
    exit 1
fi

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "Error: Python 3.10+ is required. Found ${PY_MAJOR}.${PY_MINOR}."
    exit 1
fi

echo "Python version: ${PY_MAJOR}.${PY_MINOR}"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv ..."
    python3 -m venv .venv
fi

echo "Installing Python dependencies ..."
.venv/bin/pip install -q -r requirements.txt

# Configuration prompts
echo ""
read -rp "Listen port [8080]: " PORT
PORT=${PORT:-8080}

read -rsp "Bridge API key (leave empty for no auth): " API_KEY
echo ""

# Write local env file
cat > .env <<EOF
PORT=$PORT
EOF
if [ -n "$API_KEY" ]; then
    echo "BRIDGE_API_KEY=$API_KEY" >> .env
fi
chmod 600 .env

# Render systemd service file
SERVICE_RENDERED="$REPO_DIR/antigravity-bridge.service.rendered"
sed -e "s|%USER%|$(whoami)|g" \
    -e "s|%WORK_DIR%|$REPO_DIR|g" \
    -e "s|%PYTHON_BIN_DIR%|$REPO_DIR/.venv/bin|g" \
    -e "s|%PORT%|$PORT|g" \
    -e "s|%BRIDGE_API_KEY%|$API_KEY|g" \
    -e "s|%ANTIGRAVITY_CONST%|${ANTIGRAVITY_CONST:-$HOME/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js}|g" \
    -e "s|%ANTIGRAVITY_ACCOUNTS%|${ANTIGRAVITY_ACCOUNTS:-$HOME/.config/opencode/antigravity-accounts.json}|g" \
    -e "s|%ANTIGRAVITY_AUTH%|${ANTIGRAVITY_AUTH:-$HOME/.local/share/opencode/auth.json}|g" \
    antigravity-bridge.service > "$SERVICE_RENDERED"

echo ""
echo "Installation complete."
echo ""

if command -v systemctl >/dev/null 2>&1; then
    echo "systemd detected. To run the bridge as a service (auto-restart):"
    echo ""
    echo "  sudo cp $SERVICE_RENDERED /etc/systemd/system/antigravity-bridge.service"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now antigravity-bridge"
    echo ""
    echo "To check status:"
    echo "  sudo systemctl status antigravity-bridge"
else
    echo "systemd not detected. To run the bridge manually:"
    echo ""
    echo "  source .env && .venv/bin/python3 server.py"
    echo ""
    echo "Or use nohup:"
    echo "  source .env && nohup .venv/bin/python3 server.py > bridge.log 2>&1 &"
fi

echo ""
echo "Test the bridge:"
echo "  curl -s http://127.0.0.1:$PORT/health | jq"
