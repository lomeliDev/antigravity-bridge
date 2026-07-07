<div align="center">

# 🌌 Antigravity Bridge

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI compatible](https://img.shields.io/badge/OpenAI-compatible-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)

**Standalone Google OAuth bridge for Gemini Code Assist / Antigravity — no OpenCode required.**

Built for agents and clients that do **not** support Google OAuth directly: **Hermes**, **Open WebUI**, **Continue**, **Boba**, **BetterGPT**, and any other OpenAI-compatible tool.

*Based on the `opencode-antigravity-auth` plugin OAuth flow, but fully independent.*

</div>

---

## 📖 Table of contents

- [TL;DR](#tldr)
- [What is it?](#what-is-it)
- [Quick install](#quick-install)
- [Requirements](#requirements)
- [Configuration](#configuration)
- [Manual login](#manual-login)
- [Agent setup](#agent-setup)
  - [Hermes](#hermes)
  - [Open WebUI](#open-webui)
  - [Generic OpenAI client](#generic-openai-client)
- [Supported features](#supported-features)
- [API quick tests](#api-quick-tests)
- [Common mistakes](#common-mistakes)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## ⚡ TL;DR

Run this **one command**. It installs everything, logs you in via Google OAuth, and starts the bridge as a service:

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git && \
cd antigravity-bridge && \
chmod +x install.sh scripts/*.sh && \
./install.sh
```

When the installer asks, just press **Enter** to accept the defaults. It will open your browser for Google OAuth when needed.

> **No OpenCode, no `agy` CLI, no npm packages.** Just Python and a Google account.

---

## ✨ What is it?

A small Flask bridge that uses a standalone Google OAuth `refresh_token` to access the Gemini Code Assist API. It exposes a clean **OpenAI-compatible HTTP API** so you can use it from any OpenAI-compatible client.

```text
┌─────────────┐    OpenAI API      ┌────────────────────┐    HTTPS    ┌─────────────────────────┐
│   Hermes    │ ─────────────────► │  Antigravity       │ ──────────► │  cloudcode-pa.google    │
│  Open WebUI │   /v1/chat/...     │  Bridge :PORT      │   Bearer   │  :loadCodeAssist        │
│  Continue   │                    │                    │  + project │  :generateContent       │
│             │                    │                    │            │  :streamGenerateContent │
└─────────────┘                    └────────────────────┘            └─────────────────────────┘
```

---

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
chmod +x install.sh scripts/*.sh
./install.sh
```

The installer will:

1. Check Python 3.10+ and create a virtual environment.
2. Install Python dependencies.
3. Ask how you want to authenticate:
   - **Option 1:** Paste an existing `refresh_token`.
   - **Option 2:** Interactive browser OAuth login (no CLI tools needed).
4. Ask for a **port** (default `52847`).
5. Ask whether to enable an **API key** (generates a random one by default).
6. Detect your platform and install a **systemd** (Linux) or **launchd** (macOS) daemon.
7. Run health / models / chat validation tests.

### Manual run (fallback)

```bash
./daemon/run.sh
```

Or run directly:

```bash
source .env
.venv/bin/python3 server.py --host 0.0.0.0 --port 52847
```

---

## 📋 Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or newer |
| **OS** | Linux (systemd recommended) or macOS |
| **Google account** | With access to Gemini Code Assist |
| **OAuth refresh_token** | Obtained via the installer's interactive login or `auth-login.py` |

That's it. No OpenCode, no `agy`, no npm.

---

## ⚙️ Configuration

The bridge is configured through environment variables. The installer writes them to `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Listen host |
| `PORT` | `52847` | Listen port |
| `BRIDGE_API_KEY` | *(none)* | Optional API key required from clients (`Authorization: Bearer <key>`) |
| `BRIDGE_REFRESH_TOKEN` | *(none)* | Google OAuth refresh_token — set by installer or `auth-login.py` |
| `ANTIGRAVITY_CLIENT_ID` | *(hardcoded)* | Google OAuth client ID — override only if needed |
| `ANTIGRAVITY_CLIENT_SECRET` | *(hardcoded)* | Google OAuth client secret — override only if needed |

Edit `.env` and restart the service to apply changes:

```bash
# Linux
sudo systemctl restart antigravity-bridge

# macOS
launchctl stop com.lomelidev.antigravity-bridge
launchctl start com.lomelidev.antigravity-bridge
```

---

## 🔑 Manual login

If you need to re-authenticate or set up a new token:

```bash
python3 auth-login.py
```

This will:
1. Show you a Google OAuth URL to open in your browser.
2. After authorizing, ask you to paste the redirect URL.
3. Exchange the code for tokens and save them to `.env`.

The bridge also exposes a web UI at `http://YOUR_HOST:PORT/login` with both auto (local callback) and manual login modes.

---

## 🤖 Agent setup

### Hermes

Run the helper script after `./install.sh`:

```bash
chmod +x scripts/add-to-hermes.sh
./scripts/add-to-hermes.sh
```

Or pass model and provider name directly:

```bash
./scripts/add-to-hermes.sh gemini-2.5-flash antigravity-bridge
```

It registers the bridge as a provider in `~/.hermes/config.yaml`:

```yaml
providers:
  antigravity-bridge:
    base_url: http://127.0.0.1:52847/v1
    api_key: your-bridge-api-key
    models:
      - id: gemini-2.5-flash
        name: gemini-2.5-flash

model:
  provider: antigravity-bridge
  default: gemini-2.5-flash
```

### Switching models

The bridge lists available models via `/v1/models`. Switch in Hermes:

```bash
/model antigravity-bridge:gemini-2.5-flash
/model antigravity-bridge:claude-sonnet-4-6
/model antigravity-bridge:gemini-2.5-flash-thinking
```

Or from CLI:

```bash
hermes -z "explain quantum computing" -m claude-sonnet-4-6 --provider antigravity-bridge
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
- `GET /v1/models` and `GET /v1/models/{id}` — public, no auth required
- `POST /v1/chat/completions` (blocking and SSE streaming) — requires `BRIDGE_API_KEY` if set
- Tools / functions (`tools`, `tool_choice`, multi-turn `role: "tool"`)
- Vision (`image_url` with base64 data URI or public http(s) URL)
- `response_format` (`json_object` and `json_schema`)
- `seed`, `max_tokens`, `max_completion_tokens`, `n`, `stop`, `temperature`, `top_p`
- `stream_options.include_usage`
- Hermes Dashboard compatibility stubs: `/v1/usage`, `/v1/billing/subscription`
- Optional `BRIDGE_API_KEY` client authentication
- Token refresh — access tokens are refreshed automatically; if Google ever rotates the `refresh_token`, the bridge saves it to `.env` automatically

---

## 🧪 API quick tests

```bash
BASE=http://127.0.0.1:52847
KEY="your-bridge-api-key-or-empty"
AUTH=""
[ -n "$KEY" ] && AUTH="-H Authorization: Bearer ${KEY}"

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

## 🚫 Common mistakes

| Mistake | Why it fails | What to do |
|---------|--------------|------------|
| Not having a `refresh_token` | The bridge can't authenticate. | Run `auth-login.py` or `./install.sh` and choose the interactive login. |
| Closing the terminal during the browser OAuth flow | The installer waits for you to come back. | Re-run `./install.sh` or `auth-login.py`. |
| Picking a port that is already in use | The bridge cannot start. | Choose a different port or stop the other service. |
| Forgetting the `BRIDGE_API_KEY` when connecting a client | You get `401 Unauthorized`. | Copy the key from `.env` or disable auth by removing `BRIDGE_API_KEY` from `.env`. |
| Token expired after 6 months of inactivity | Google revokes unused refresh tokens. | Run `auth-login.py` to get a new one. |

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Bridge fails to start | Run manually to see the error: `source .env && .venv/bin/python3 server.py` |
| `Missing OAuth credentials` at startup | Set `BRIDGE_REFRESH_TOKEN` in `.env` or run `auth-login.py`. |
| `401 Unauthorized` from upstream | The refresh token may be revoked. Run `auth-login.py` to get a new one. |
| Models list is empty | The bridge couldn't refresh the token. Check `.env` and run `auth-login.py`. |
| MCP servers fail with `uv`/`uvx` not found | Run `./install.sh` again — it auto-installs `uv`/`uvx`. |

---

## ⚠️ Disclaimer

This is an **unofficial, experimental** project. The author is not affiliated with Google, Antigravity, Gemini Code Assist, or any other mentioned service.

By installing and using this software you agree that:

- You use it **at your own risk**.
- The author is **not responsible** for account bans, suspensions, rate-limit issues, data loss, security incidents, or any other consequences.
- You are solely responsible for complying with the terms of service of any third-party service you access through this bridge.

See [DISCLAIMER.md](DISCLAIMER.md) for the full text.

---

## 📄 License

[MIT](LICENSE) © [@lomeliDev](https://github.com/lomeliDev)

---

<div align="center">

**Made with 💜 so you can use Antigravity everywhere.**

</div>
