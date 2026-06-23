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

- [TL;DR](#tldr)
- [What is it?](#what-is-it)
- [Quick install](#quick-install)
- [Before you begin](#before-you-begin)
- [Requirements](#requirements)
- [Configuration](#configuration)
- [Agent setup](#agent-setup)
  - [Hermes](#hermes)
  - [OpenClaw](#openclaw)
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

Run this **one command**. It installs everything, logs you in, and starts the bridge as a service:

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git && \
cd antigravity-bridge && \
chmod +x install.sh scripts/*.sh && \
./install.sh
```

When the installer asks, just press **Enter** to accept the defaults. It will open your browser for Google OAuth when needed.

> **You do NOT need to run `agy login` or `opencode auth login` yourself.** The installer does it for you.

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

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
chmod +x install.sh scripts/*.sh
./install.sh
```

The installer will:

1. Install the OpenCode CLI if it is missing.
2. Install the Antigravity CLI (`agy`) if it is missing.
3. Run `agy login` for you if no session exists. *(A browser tab will open — just log in.)*
4. Add the `opencode-antigravity-auth` plugin to OpenCode if it is missing.
5. Run `opencode auth login` for you if no Google OAuth credential exists. *(Another browser tab — same account.)*
6. Validate the Antigravity credential files.
7. Check Python 3.10+ and create a virtual environment.
8. Install Python dependencies.
9. Ask for a **port** (default `52847`).
10. Ask whether to enable an **API key / password** (generates a random one by default).
11. Detect your platform and install a **systemd** (Linux) or **launchd** (macOS) daemon automatically.
12. Run health / models validation tests.

> **Do not run `agy login` or `opencode auth login` before `./install.sh`.** The installer handles the OAuth flows. If you already did them, the installer will detect them and skip those steps.

### Manual run (fallback)

If the installer cannot install a daemon, it creates a portable runner:

```bash
./daemon/run.sh
```

Or run directly:

```bash
source .env
.venv/bin/python3 server.py --host 0.0.0.0 --port 52847
```

---

## 🎯 Before you begin

The bridge **reuses** the Google OAuth session created by OpenCode. You must complete these steps **once** before the bridge can authenticate with Antigravity.

**You can skip this section if you run `./install.sh`.** The installer does everything below automatically. This section is only for people who want to set things up manually.

### 1. Install the OpenCode CLI

```bash
curl -fsSL https://opencode.ai/install | bash
opencode --version
```

### 2. Install the Antigravity CLI (`agy`)

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
agy --version
```

### 3. Log in with `agy`

```bash
agy login
```

> If your version of `agy` does not have a `login` subcommand, just run `agy` and complete the first-run OAuth wizard.

### 4. Add the Antigravity auth plugin to OpenCode

```bash
mkdir -p ~/.config/opencode
cat > ~/.config/opencode/opencode.json <<'EOF'
{
  "plugin": ["opencode-antigravity-auth@latest"]
}
EOF
```

### 5. Log in with OpenCode

```bash
opencode auth login
```

Select:

- **Provider:** `Google`
- **Method:** `OAuth with Google (Antigravity)**

Sign in with the **same** Google account you used for `agy login`.

### 6. Verify the credential was stored

```bash
opencode auth list
```

You should see a `Google oauth` entry.

### 7. Where the credential files live

After login you will have:

```text
~/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js
~/.config/opencode/antigravity-accounts.json
~/.local/share/opencode/auth.json
```

---

## 📋 Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or newer |
| **OS** | Linux (systemd recommended) or macOS |
| **OpenCode CLI** | Installed (`curl -fsSL https://opencode.ai/install \| bash`) |
| **Antigravity CLI** | Installed and logged in (`agy login`) |
| **Antigravity auth plugin** | `opencode-antigravity-auth` configured in `~/.config/opencode/opencode.json` |
| **OpenCode auth** | `opencode auth login` completed with Google → OAuth with Google (Antigravity) |
| **Credential files** | The three files listed above must exist |

If any prerequisite is missing, the installer stops and tells you exactly what to do.

---

## ⚙️ Configuration

The bridge is configured through environment variables. The installer writes them to `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `127.0.0.1` | Listen host |
| `PORT` | `52847` | Listen port |
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
chmod +x scripts/add-to-hermes.sh
./scripts/add-to-hermes.sh
```

The script will ask you for a **model id** and a **provider name**. Just press Enter to accept the defaults (`gemini-2.5-flash` and `antigravity-bridge`).

You can also pass them as arguments to skip the prompts:

```bash
./scripts/add-to-hermes.sh gemini-2.5-flash my-antigravity
```

It only **registers** the bridge as a named custom provider in `~/.hermes/config.yaml`. It does **not** change your active model or default provider — you choose those in Hermes yourself.

At the end the script asks if you want to restart the Hermes gateway and shows the status before and after:

```yaml
custom_providers:
  - name: antigravity-bridge
    base_url: http://127.0.0.1:52847/v1
    api_key: your-bridge-api-key          # only if you enabled auth
    api_mode: chat_completions
    models:
      - id: gemini-2.5-flash
        name: gemini-2.5-flash
```

If you skipped the automatic restart, do it manually:

```bash
hermes gateway restart     # if you use the Hermes gateway
# or close and reopen Hermes if you use the CLI/TUI
```

Then pick the provider in the Hermes panel, or run:

```bash
/model custom:antigravity-bridge:gemini-2.5-flash
```

### OpenClaw

Run the helper script after `./install.sh`:

```bash
chmod +x scripts/add-to-openclaw.sh
./scripts/add-to-openclaw.sh
```

The script will ask you for a **model id** and a **provider name**. Just press Enter to accept the defaults (`gemini-2.5-flash` and `antigravity-bridge`).

You can also pass them as arguments to skip the prompts:

```bash
./scripts/add-to-openclaw.sh gemini-2.5-flash my-antigravity
```

It edits `~/.openclaw/openclaw.json` (creating it if necessary) and adds the bridge as a custom provider:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "antigravity-bridge": {
        "baseUrl": "http://127.0.0.1:52847/v1",
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

At the end the script asks if you want to apply the config and restart the OpenClaw gateway, and shows the status before and after.

If you skipped the automatic restart, apply the config manually:

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
BASE=http://127.0.0.1:52847
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

## 🚫 Common mistakes

| Mistake | Why it fails | What to do |
|---------|--------------|------------|
| Running `agy login` or `opencode auth login` manually before `./install.sh` | Nothing breaks, but it is unnecessary. The installer does it automatically and skips the steps if it detects a session. | Just run `./install.sh`. |
| Closing the terminal during the browser OAuth flow | The installer waits for you to come back. If you close it, the login never finishes. | Re-run `./install.sh`. |
| Running `./install.sh` with `sudo` | The bridge will be configured for `root` and the service will run as `root`, which is usually not what you want. | Run as your normal user. |
| Picking a port that is already in use | The bridge cannot start. | Re-run `./install.sh` and choose a different port, or stop the other service. |
| Forgetting the `BRIDGE_API_KEY` when connecting a client | You get `401 Unauthorized`. | Copy the key from `.env` or disable auth by removing `BRIDGE_API_KEY` from `.env`. |
| Using a different Google account for `agy login` and `opencode auth login` | The credentials may not match and the bridge can fail to refresh tokens. | Use the **same** Google account for both logins. |

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

## ⚠️ Disclaimer

This is an **unofficial, experimental** project. The author is not affiliated with Google, Antigravity, Gemini Code Assist, OpenCode, or any other mentioned service.

By installing and using this software you agree that:

- You use it **at your own risk**.
- The author is **not responsible** for account bans, suspensions, rate-limit issues, data loss, security incidents, or any other consequences.
- You are solely responsible for complying with the terms of service of any third-party service you access through this bridge.

The author created this project "just for fun". Be conscious of what you do with it.

See [DISCLAIMER.md](DISCLAIMER.md) for the full text.

---

## 📄 License

[MIT](LICENSE) © [@lomeliDev](https://github.com/lomeliDev)

---

<div align="center">

**Made with 💜 so you can use Antigravity everywhere.**

</div>
