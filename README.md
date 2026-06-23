<div align="center">

# 🌌 Antigravity Bridge

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI compatible](https://img.shields.io/badge/OpenAI-compatible-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)

**Turn your [Antigravity](https://www.antigravity.ai/) / Gemini Code Assist Google OAuth session into an OpenAI-compatible API.**

Built for agents and clients that do **not** support Google OAuth directly: **Hermes**, **OpenClaw**, **Open WebUI**, **Continue**, **Boba**, **BetterGPT**, and any other OpenAI-compatible tool.

</div>

---

## 📖 Table of contents

- [What is it?](#what-is-it)
- [Before you begin](#before-you-begin)
- [Requirements](#requirements)
- [Quick install](#quick-install)
- [Configuration](#configuration)
- [Agent setup](#agent-setup)
  - [Hermes](#hermes)
  - [OpenClaw](#openclaw)
  - [Open WebUI](#open-webui)
  - [Generic OpenAI client](#generic-openai-client)
- [Supported features](#supported-features)
- [API quick tests](#api-quick-tests)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## ✨ What is it?

Your Antigravity / OpenCode IDE extension is already authenticated and keeps valid tokens in `~/.local/share/opencode/auth.json`. This small Flask bridge exposes those credentials through a clean **OpenAI-compatible HTTP API**, so you can reuse your account from any client that speaks the OpenAI protocol.

```text
┌─────────────┐    OpenAI API      ┌────────────────────┐    HTTPS    ┌─────────────────────────┐
│   Hermes    │ ─────────────────► │  Antigravity       │ ──────────► │  cloudcode-pa.google    │
│  OpenClaw   │   /v1/chat/...     │  Bridge :PORT      │   Bearer   │  :loadCodeAssist        │
│  Open WebUI │                    │                    │  + project │  :generateContent       │
│  Continue   │                    │                    │            │  :streamGenerateContent │
└─────────────┘                    └────────────────────┘            └─────────────────────────┘
```

---

## 🎯 Before you begin

The bridge **reuses** the Google OAuth session created by OpenCode. You must complete these steps **once** before installing the bridge:

### 1. Install the OpenCode CLI

Download and install it from [opencode.ai](https://opencode.ai), then verify it is on your `PATH`:

```bash
opencode --version
```

### 2. Install the Antigravity auth plugin

Add the official plugin to your OpenCode config. The installer can do this for you, or you can do it manually:

```bash
mkdir -p ~/.config/opencode
cat > ~/.config/opencode/opencode.json <<'EOF'
{
  "plugin": ["opencode-antigravity-auth@latest"]
}
EOF
```

> The plugin lives at `~/.cache/opencode/packages/opencode-antigravity-auth@latest/...` and provides the OAuth client id/secret the bridge needs.

### 3. Log in with Google

Run the OpenCode auth wizard and choose the Antigravity OAuth flow:

```bash
opencode auth login
```

Select:

- **Provider:** `Google`
- **Method:** `OAuth with Google (Antigravity)`

Sign in with the Google account that has Antigravity access. When the browser flow finishes, verify the credential is stored:

```bash
opencode auth list
```

You should see a `Google oauth` entry.

### 4. Where the credential files live

After login you will have:

```text
~/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js
~/.config/opencode/antigravity-accounts.json
~/.local/share/opencode/auth.json
```

The installer checks these paths automatically.

---

## 📋 Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or newer |
| **OS** | Linux (systemd recommended) or macOS |
| **OpenCode CLI** | Installed and authenticated (see [Before you begin](#before-you-begin)) |
| **Antigravity auth plugin** | `opencode-antigravity-auth` configured in `~/.config/opencode/opencode.json` |
| **Credential files** | The three files listed above must exist |

If any prerequisite is missing, the installer stops and tells you exactly what to do.

---

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

The installer will:

1. Check the OpenCode CLI, the Antigravity auth plugin, and the credential files.
2. Check Python 3.10+ and create a virtual environment.
3. Install Python dependencies.
4. Ask for a **port** (default `8080`).
5. Ask whether to enable an **API key** (generates a random one by default).
6. Detect your platform and install a **systemd** (Linux) or **launchd** (macOS) daemon automatically.
7. Run health / models validation tests.

### Manual run (fallback)

If the installer cannot install a daemon, it creates a portable runner:

```bash
./daemon/run.sh
```

Or run directly:

```bash
source .env
.venv/bin/python3 server.py --host 0.0.0.0 --port 8080
```

---

## ⚙️ Configuration

The bridge is configured through environment variables. The installer writes them to `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `127.0.0.1` | Listen host |
| `PORT` | `8080` | Listen port |
| `BRIDGE_API_KEY` | *(none)* | Optional API key required from clients (`Authorization: Bearer <key>`) |
| `ANTIGRAVITY_CONST` | `~/.cache/opencode/.../constants.js` | OAuth client id/secret |
| `ANTIGRAVITY_ACCOUNTS` | `~/.config/opencode/antigravity-accounts.json` | Account + refresh token |
| `ANTIGRAVITY_AUTH` | `~/.local/share/opencode/auth.json` | Cached access token + project id |

Edit `.env` and restart the service to apply changes:

```bash
# Linux
sudo systemctl restart antigravity-bridge

# macOS
launchctl stop com.lomelidev.antigravity-bridge
launchctl start com.lomelidev.antigravity-bridge
```

---

## 🤖 Agent setup

The bridge is meant to be consumed by agents and clients that do not support Google OAuth themselves.

### Hermes

Run the helper script after `./install.sh`:

```bash
./scripts/add-to-hermes.sh
```

It reads `.env` and runs the Hermes CLI commands for you:

```bash
hermes config set model.provider custom
hermes config set model.base_url http://127.0.0.1:8080/v1
hermes config set model.api_key your-bridge-api-key   # only if you enabled auth
hermes config set model.default gemini-2.5-flash
```

Then start Hermes and switch models with:

```bash
/model gemini-2.5-flash
```

### OpenClaw

Run the helper script after `./install.sh`:

```bash
./scripts/add-to-openclaw.sh
```

It edits `~/.openclaw/openclaw.json` (creating it if necessary) and adds the bridge as a custom provider:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "antigravity-bridge": {
        "baseUrl": "http://127.0.0.1:8080/v1",
        "api": "openai-completions",
        "apiKey": "your-bridge-api-key",
        "models": [{ "id": "gemini-2.5-flash", "name": "gemini-2.5-flash" }]
      }
    }
  },
  "agents": {
    "defaults": {
      "models": {
        "antigravity-bridge/gemini-2.5-flash": { "alias": "gemini-2.5-flash" }
      }
    }
  }
}
```

Apply the config and restart the gateway:

```bash
openclaw gateway config.apply --file ~/.openclaw/openclaw.json
```

Then in chat:

```bash
/model gemini-2.5-flash
```

### Open WebUI

1. Go to **Admin Panel → Settings → Connections**.
2. Add an OpenAI API connection.
3. Set **URL** to `http://YOUR_SERVER_IP:PORT/v1`.
4. Set **Key** to your `BRIDGE_API_KEY` (or any placeholder if auth is disabled).
5. Save — the model list will populate automatically.

### Generic OpenAI client

| Field | Value |
|-------|-------|
| **Base URL** | `http://YOUR_SERVER_IP:PORT/v1` |
| **API key** | Your `BRIDGE_API_KEY` value, or any non-empty string if auth is disabled |
| **Models** | Fetched automatically from `GET /v1/models` |

---

## 🧩 Supported features

- `GET /health`
- `GET /v1/models` and `GET /v1/models/{id}` (dynamically fetched from Antigravity)
- `POST /v1/chat/completions` (blocking and SSE streaming)
- Tools / functions (`tools`, `tool_choice`, multi-turn `role: "tool"`)
- Vision (`image_url` with base64 data URI or public http(s) URL)
- `response_format` (`json_object` and `json_schema`)
- `seed`, `max_tokens`, `max_completion_tokens`, `n`, `stop`, `temperature`, `top_p`
- `stream_options.include_usage`
- Optional `BRIDGE_API_KEY` client authentication

> **Note:** `logprobs`, `frequency_penalty`, `presence_penalty`, and `logit_bias` are not supported by the Antigravity upstream and are silently ignored.

---

## 🧪 API quick tests

```bash
BASE=http://127.0.0.1:8080
KEY="your-bridge-api-key-or-empty"
AUTH=""
[ -n "$KEY" ] && AUTH="-H Authorization: Bearer $KEY"

# Health check
curl -s $AUTH "$BASE/health" | jq

# List models
curl -s $AUTH "$BASE/v1/models" | jq '.data[].id'

# Chat completion
curl -s "$BASE/v1/chat/completions" \
  $AUTH \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "hello"}]
  }' | jq

# Streaming
curl -N "$BASE/v1/chat/completions" \
  $AUTH \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-flash",
    "stream": true,
    "messages": [{"role": "user", "content": "tell me a joke"}]
  }'
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| `opencode CLI not found` | Install OpenCode first: https://opencode.ai |
| `opencode-antigravity-auth plugin is not configured` | Run the installer and let it add the plugin, or add it manually as shown in [Before you begin](#before-you-begin). |
| `No Antigravity credentials found` | Run `opencode auth login`, select Google → OAuth with Google (Antigravity), and finish the browser login. |
| Port already in use | Pick a different port during install or stop the other service. |
| `401 Unauthorized` | Set `Authorization: Bearer <BRIDGE_API_KEY>` in your client, or disable the API key in `.env`. |
| Models list is empty | The bridge could not refresh the Antigravity token. Check `bridge.log` and verify the credential files are valid. |
| Service fails to start | Run the bridge manually to see the error: `source .env && .venv/bin/python3 server.py` |

---

## 📄 License

[MIT](LICENSE) © [@lomeliDev](https://github.com/lomeliDev)

---

<div align="center">

**Made with 💜 so you can use Antigravity everywhere.**

</div>
