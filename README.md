<div align="center">

# 🌌 Antigravity Bridge

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI compatible](https://img.shields.io/badge/OpenAI-compatible-412991?logo=openai&logoColor=white)](https://platform.openai.com/docs/api-reference)

**Standalone Google OAuth bridge for Gemini Code Assist / Antigravity. Multi-account. No OpenCode required.**

Built for agents and clients that do **not** support Google OAuth directly: **Hermes**, **Open WebUI**, **Continue**, **Boba**, **BetterGPT**, and any other OpenAI-compatible tool.

</div>

---

## 📖 Table of contents

- [TL;DR](#tldr)
- [What is it?](#what-is-it)
- [Quick install](#quick-install)
- [Architecture](#architecture)
  - [Single-account (simple)](#single-account-simple)
  - [Multi-account](#multi-account)
- [Configuration](#configuration)
- [Account management (admin API)](#account-management-admin-api)
- [OAuth login](#oauth-login)
- [Agent setup](#agent-setup)
  - [Hermes](#hermes)
  - [LiteLLM](#litellm)
  - [Open WebUI](#open-webui)
  - [Generic OpenAI client](#generic-openai-client)
- [API reference](#api-reference)
- [Supported features](#supported-features)
- [API quick tests](#api-quick-tests)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## ⚡ TL;DR

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
chmod +x install.sh
./install.sh
```

The installer handles Python venv, OAuth login (opens your browser), and installs the service. **One command.**

> No OpenCode, no `agy` CLI, no npm packages. Just Python + a Google account.

---

## ✨ What is it?

A Flask bridge that uses **Google OAuth refresh_tokens** to access **Gemini Code Assist** (Antigravity). It talks the **OpenAI-compatible HTTP API** so any client that works with OpenAI can work with Gemini Code Assist — **including Claude and GPT models proxied through Google's platform**.

```
┌─────────────┐   OpenAI API     ┌────────────────────┐   HTTPS    ┌─────────────────────────┐
│   Hermes    │ ────────────────► │  Antigravity       │ ─────────► │  cloudcode-pa.google    │
│  Open WebUI │  /v1/chat/...    │  Bridge :PORT       │  Bearer   │  Gemini · Claude · GPT  │
│  LiteLLM    │                  │                     │  + OAuth  │  14 models              │
└─────────────┘                  └────────────────────┘           └─────────────────────────┘
```

**14 models** across 3 providers through a single bridge: Gemini (2.5, 3, 3.1, 3.5), Claude (Sonnet, Opus), GPT.

---

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
chmod +x install.sh
./install.sh
```

What the installer does:

1. Checks Python 3.10+ and creates a `.venv`.
2. Installs `flask` + `requests`.
3. **OAuth login** — opens your browser, you authorize Google, paste the redirect URL.
4. Asks for port and optional API key.
5. Installs a **systemd** (Linux) or **launchd** (macOS) service.
6. Runs health + models + chat validation.

### Manual run

```bash
source .env
.venv/bin/python3 server.py --host 0.0.0.0 --port 52847
```

---

## 🏗️ Architecture

### Single-account (simple)

Default setup with env vars — good for personal use:

```
.env:
  BRIDGE_REFRESH_TOKEN=1//...    ← one Google account
  BRIDGE_API_KEY=sk-...          ← optional client auth

→ All requests go through that one account.
```

### Multi-account

One bridge process → unlimited Google accounts → one API key per account:

```
accounts.json:
{
  "accounts": {
    "sk-account-one-xxxxxxxxxxxx": {
      "label": "Miguel Personal",
      "refresh_token": "1//...",
      "client_id": "...",
      "client_secret": "..."
    },
    "sk-account-two-yyyyyyyyyyyy": {
      "label": "Work Account", 
      "refresh_token": "1//..."
    }
  }
}

Authorization: Bearer <your-account-key>  → Miguel's account
Authorization: Bearer <your-work-key>      → Work account
```

Each account gets its own **access token cache** in `auth_cache/`, its own rate limits, and its own model access. Perfect for teams, agencies, or power users.

---

## ⚙️ Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Listen host |
| `PORT` | `52847` | Listen port |
| `BRIDGE_REFRESH_TOKEN` | — | OAuth refresh_token (single-account mode) |
| `BRIDGE_API_KEY` | — | Client API key (deprecated — use accounts.json for multi-account) |
| `BRIDGE_ADMIN_KEY` | — | Protects `/admin/*` endpoints. If empty → open access (dev mode) |
| `BRIDGE_ACCOUNTS_FILE` | `./accounts.json` | Path to multi-account config |
| `BRIDGE_AUTH_CACHE_DIR` | `./auth_cache/` | Per-account token cache directory |
| `ANTIGRAVITY_CLIENT_ID` | *(hardcoded)* | Google OAuth client ID |
| `ANTIGRAVITY_CLIENT_SECRET` | *(hardcoded)* | Google OAuth client secret |

---

## 👥 Account management (admin API)

Protected by `BRIDGE_ADMIN_KEY` (set in `.env`). All admin calls require `Authorization: Bearer <admin_key>`.

### Create an account

```bash
curl -X POST http://127.0.0.1:52848/admin/accounts \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-my-new-account", "label": "My New Account"}'
```

Response: `{"ok": true, "api_key": "sk-my-new-account"}`

### Start OAuth login for the new account

```bash
curl -X POST http://127.0.0.1:52848/admin/accounts/sk-my-new-account/login \
  -H "Authorization: Bearer <admin_key>"
```

Returns an `auth_url` — open it in your browser, authorize Google, and the bridge captures the code automatically (localhost callback). Or use manual mode:

```bash
# After authorizing in browser, copy the redirect URL and:
curl -X POST http://127.0.0.1:52848/auth/login/manual \
  -H "Content-Type: application/json" \
  -d '{"code": "..."}'
```

### List all accounts

```bash
curl http://127.0.0.1:52848/admin/accounts \
  -H "Authorization: Bearer <admin_key>"
```

### Remove an account

```bash
curl -X DELETE http://127.0.0.1:52848/admin/accounts/sk-my-new-account \
  -H "Authorization: Bearer <admin_key>"
```

### Use the account

```bash
curl http://127.0.0.1:52848/v1/chat/completions \
  -H "Authorization: Bearer sk-my-new-account" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hello"}]}'
```

### Full flow from scratch

```
POST /admin/accounts          → create account (empty, no token yet)
POST /admin/accounts/X/login  → get auth_url
→ user opens URL in browser
→ authorizes Google
→ localhost:51121 captures code automatically
POST /auth/login/callback     → exchanges code for tokens
✅ Account ready — refresh_token saved to accounts.json
```

---

## 🔑 OAuth login

### Interactive (browser)

```bash
python3 auth-login.py
```

Opens your browser, captures the OAuth redirect on `localhost:51121`.

### Web UI

Open `http://YOUR_HOST:PORT/login` in your browser — dual mode (auto callback + manual code paste).

### Manual (remote servers)

```bash
# 1. Get auth URL
curl -X POST http://YOUR_HOST:52848/auth/login

# 2. Open the returned auth_url in a browser, authorize

# 3. Copy the redirect URL and exchange:
curl -X POST http://YOUR_HOST:52848/auth/login/manual \
  -H "Content-Type: application/json" \
  -d '{"code": "PASTE_FULL_REDIRECT_URL_HERE"}'
```

---

## 🤖 Agent setup

### Hermes

```bash
./scripts/add-to-hermes.sh gemini-2.5-flash antigravity-bridge
```

### LiteLLM

Add to `litellm_config.yaml`:

```yaml
model_list:
  - model_name: gemini-2.5-flash
    litellm_params:
      model: openai/gemini-2.5-flash
      api_base: http://127.0.0.1:52848/v1
      api_key: sk-your-account-key
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: openai/claude-sonnet-4-6
      api_base: http://127.0.0.1:52848/v1
      api_key: sk-your-account-key
```

### Open WebUI

1. Admin Panel → Settings → Connections → Add OpenAI API.
2. URL: `http://YOUR_SERVER:52848/v1`
3. Key: your account API key (from `accounts.json`).

### Generic OpenAI client

| Field | Value |
|-------|-------|
| Base URL | `http://YOUR_SERVER:52848/v1` |
| API key | Account key (`sk-...`) from `accounts.json` |
| Models | Fetched via `GET /v1/models` |

---

## 📡 API reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/` | — | Bridge info + account count |
| `GET` | `/health` | — | Health + credential status |
| `GET` | `/v1/models` | — | List all models |
| `GET` | `/v1/models/{id}` | — | Single model info |
| `POST` | `/v1/chat/completions` | Account key | Chat (stream + non-stream) |
| `GET` | `/v1/usage` | — | Per-model usage stats |
| `GET` | `/v1/billing/subscription` | — | Billing stub (Hermes compat) |
| `GET` | `/admin/accounts` | Admin key | List accounts |
| `POST` | `/admin/accounts` | Admin key | Create account |
| `DELETE` | `/admin/accounts/{key}` | Admin key | Remove account |
| `POST` | `/admin/accounts/{key}/login` | Admin key | Start OAuth for account |
| `POST` | `/auth/login` | — | Start OAuth (default account) |
| `POST` | `/auth/login/callback` | — | Exchange captured code |
| `POST` | `/auth/login/manual` | — | Exchange pasted code |
| `GET` | `/auth/login/status` | — | Auth status |
| `GET` | `/login` | — | Web UI login page |

---

## 🧩 Supported features

- `POST /v1/chat/completions` — blocking and SSE streaming
- Multi-turn conversations with tool calls (`tools`, `tool_choice`, `role: "tool"`)
- Vision — `image_url` with base64 data URI or public URL (7/8 models tested ✅)
- `response_format` — `json_object` and `json_schema`
- `seed`, `max_tokens`, `max_completion_tokens`, `n`, `stop`, `temperature`, `top_p`
- `stream_options.include_usage`
- Hermes Dashboard compatibility: `/v1/usage`, `/v1/billing/subscription`
- Automatic token refresh — access tokens refreshed transparently
- Auto-clear on `invalid_grant` — revoked tokens are detected and cleaned
- PKCE (S256) OAuth security
- Multi-account — one bridge, N Google accounts, N API keys
- Admin API with optional `BRIDGE_ADMIN_KEY` protection

---

## 🧪 API quick tests

```bash
BASE=http://127.0.0.1:52848

# Health
curl -s "$BASE/health" | jq

# Models
curl -s "$BASE/v1/models" | jq '.data[].id'

# Chat (no key, single-account mode)
curl -s "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hi"}]}' | jq

# Chat (with account key, multi-account mode)
curl -s "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer sk-your-account" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"hi"}]}' | jq

# Streaming
curl -N "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","stream":true,"messages":[{"role":"user","content":"tell me a joke"}]}'

# Usage
curl -s "$BASE/v1/usage" | jq

# Vision (image URL)
curl -s "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":[{"type":"text","text":"What do you see?"},{"type":"image_url","image_url":{"url":"https://example.com/photo.jpg"}}]}]}' | jq
```

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Bridge fails to start | Run manually: `source .env && .venv/bin/python3 server.py` |
| `Missing OAuth credentials` | Account has no refresh_token. Run OAuth login for that account. |
| `401 Invalid API key` | The account key doesn't match any in `accounts.json`. Check with `GET /admin/accounts`. |
| `invalid_grant` from Google | Token revoked. The bridge auto-clears it. Run login again. |
| Models list is empty | Token refresh failed. Check `GET /health` for credential status. |
| Admin `401` | Set `BRIDGE_ADMIN_KEY` in `.env` and pass it as `Authorization: Bearer <admin_key>`. |

---

## ⚠️ Disclaimer

This is an **unofficial, experimental** project. Not affiliated with Google, Antigravity, or Gemini Code Assist.

Use at your own risk. See [DISCLAIMER.md](DISCLAIMER.md).

---

## 📄 License

[MIT](LICENSE) © [@lomeliDev](https://github.com/lomeliDev)

---

<div align="center">

**Made with 💜 so you can use Antigravity everywhere.**

</div>
