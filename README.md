<div align="center">

# 🌌 Antigravity Bridge

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI compatible](https://img.shields.io/badge/OpenAI-compatible-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)

**Turn your [Antigravity](https://www.antigravity.ai/) / Gemini Code Assist Google OAuth session into an OpenAI-compatible API.**

Use it with **Hermes**, **Open WebUI**, **Boba**, **BetterGPT**, **Continue**, or any other OpenAI client.

</div>

---

## 📖 Table of contents

- [What is it?](#what-is-it)
- [Requirements](#requirements)
- [Quick install](#quick-install)
- [Configuration](#configuration)
- [Connect your client](#connect-your-client)
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
│  Open WebUI │   /v1/chat/...     │  Bridge :PORT      │   Bearer   │  :loadCodeAssist        │
│    Boba     │                    │                    │  + project │  :generateContent       │
│  Continue   │                    │                    │            │  :streamGenerateContent │
└─────────────┘                    └────────────────────┘            └─────────────────────────┘
```

---

## 📋 Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or newer |
| **OS** | Linux (systemd recommended) or macOS |
| **Antigravity account** | Already signed in through OpenCode / the Antigravity IDE extension |
| **Credential files** | The installer checks these default paths (you can override them with environment variables): |

```text
~/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js
~/.config/opencode/antigravity-accounts.json
~/.local/share/opencode/auth.json
```

If any file is missing, the installer warns you but lets you continue — the bridge simply cannot authenticate without them.

---

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

The installer will:

1. Check Python 3.10+ and create a virtual environment.
2. Install Python dependencies.
3. Validate your Antigravity credential files.
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

## 🔌 Connect your client

Point your OpenAI-compatible client to the bridge:

| Field | Value |
|-------|-------|
| **Base URL** | `http://YOUR_SERVER_IP:PORT/v1` |
| **API key** | Your `BRIDGE_API_KEY` value, or any non-empty string if auth is disabled |
| **Models** | Fetched automatically from `GET /v1/models` |

### Hermes example

```json
{
  "api_type": "openai",
  "base_url": "http://127.0.0.1:8080/v1",
  "api_key": "sk-local-or-your-bridge-key",
  "model": "gemini-2.5-flash"
}
```

### Open WebUI example

1. Go to **Admin Panel → Settings → Connections**.
2. Add an OpenAI API connection.
3. Set **URL** to `http://YOUR_SERVER_IP:PORT/v1`.
4. Set **Key** to your `BRIDGE_API_KEY` (or any placeholder if auth is disabled).
5. Save — the model list will populate automatically.

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
| `No Antigravity credentials found` | Sign in to the Antigravity / OpenCode extension at least once so it writes the credential files listed in [Requirements](#requirements). |
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
