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

The installer handles the Python venv, asks for the Antigravity OAuth client (see below), runs the OAuth login (opens your browser), writes `.env` and installs the service. **One command.**

> No OpenCode, no `agy` CLI required at runtime. Just Python + a Google AI Pro/Ultra account.

**You need two values before installing** — Antigravity's public OAuth client id/secret. They are not in the repo
(GitHub blocks commits containing them). Get them once from the `opencode-antigravity-auth` npm package:

```bash
npm pack opencode-antigravity-auth && tar xzf opencode-antigravity-auth-*.tgz
grep -rho 'CLIENT_[A-Z]* = "[^"]*' package/
```

The installer prompts for them and stores them in `.env` (`ANTIGRAVITY_CLIENT_ID`, `ANTIGRAVITY_CLIENT_SECRET`).

---

## ✨ What is it?

A Flask bridge that uses **Google OAuth refresh_tokens** to access **Gemini Code Assist** (Antigravity). It talks the **OpenAI-compatible HTTP API** so any client that works with OpenAI can work with Gemini Code Assist — **including Claude and GPT models proxied through Google's platform**.

```
┌─────────────┐   OpenAI API     ┌────────────────────┐   HTTPS    ┌─────────────────────────┐
│   Hermes    │ ────────────────► │  Antigravity       │ ─────────► │  daily-cloudcode-pa     │
│  Open WebUI │  /v1/chat/...    │  Bridge :PORT       │  Bearer   │  Gemini · Claude · GPT  │
│  LiteLLM    │                  │                     │  + OAuth  │  ~25 models             │
└─────────────┘                  └────────────────────┘           └─────────────────────────┘
```

**~25 models** across 3 providers through a single bridge: Gemini (2.5 → 3.8 Flash/Pro with low/medium/high effort, image), Claude (Sonnet 4.6, Opus 4.6), GPT-OSS — plus Google Search grounding, URL reading and code execution.

---

## 🚀 Quick install

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
chmod +x install.sh
./install.sh
```

What the installer does:

1. Checks Python 3.10+ and creates a `.venv`, installs `flask` + `requests`.
2. Asks for **`ANTIGRAVITY_CLIENT_ID` / `ANTIGRAVITY_CLIENT_SECRET`** (prefilled if already in `.env`).
3. **OAuth login** (standalone PKCE, no server needed) — prints a Google link, you authorize, paste the redirect URL.
   Or paste an existing refresh_token, or keep the one already in `.env`.
4. Asks for port and optional client API key.
5. Writes `.env` (preserving existing values) and the daemon files.
6. Installs a **systemd** (Linux) or **launchd** (macOS) service and runs the smoke test:
   `/health`, `/v1/models`, `/v1/chat/completions`, `/v1/quota`, `/docs`.

Re-running `install.sh` is safe: it keeps your `.env` values and offers to keep the current token.

### Manual run

```bash
.venv/bin/python3 server.py --host 0.0.0.0 --port 52847   # server.py loads .env by itself
```

Then open `http://127.0.0.1:52847/docs` (Swagger UI).

### Upgrading from the July version

The backend now requires the OAuth scope `aicode`; refresh tokens created before Sep 2026 get `401`.
After `git pull`: add `ANTIGRAVITY_CLIENT_ID/SECRET` to `.env`, delete `auth_cache/` and `accounts.json` (or the
old `BRIDGE_REFRESH_TOKEN`), run `python3 auth-login.py`, restart.

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
| `BRIDGE_DEBUG` | `0` | `1` = full tracebacks + upstream request log (includes base64 images; keep `0` in prod) |
| `BRIDGE_REFRESH_TOKEN` | — | OAuth refresh_token (single-account mode). Must have the `aicode` scope (re-login if created before Sep 2026) |
| `BRIDGE_API_KEY` | — | Client API key (deprecated — use accounts.json for multi-account) |
| `BRIDGE_ADMIN_KEY` | — | Protects `/admin/*` endpoints. If empty → open access (dev mode) |
| `BRIDGE_ACCOUNTS_FILE` | `./accounts.json` | Path to multi-account config |
| `BRIDGE_AUTH_CACHE_DIR` | `./auth_cache/` | Per-account token cache directory |
| `ANTIGRAVITY_CLIENT_ID` | — | **Required.** Antigravity's OAuth client id (public; not in repo — see Quick install) |
| `ANTIGRAVITY_CLIENT_SECRET` | — | **Required.** Antigravity's OAuth client secret (public, PKCE desktop client) |
| `ANTIGRAVITY_ASSIST_URL` | `https://daily-cloudcode-pa.googleapis.com/v1internal` | Backend endpoint |
| `AGY_CLI_VERSION` / `AGY_CLI_CL` / `AGY_AUTH_METHOD` | `1.1.28` / `978129418` / `consumer` | User-Agent fingerprint of the Antigravity CLI |
| `AGY_CONSUMER_PROJECT` | `aicode-consumers` | `project` sent with consumer auth |
| `BRIDGE_QUOTA_TTL` | `30` | Seconds to cache `/v1/quota` |
| `BRIDGE_RESOLVE_CITATIONS` | `0` | Resolve grounding citation redirects to the real URL |

`.env` is loaded by `server.py` itself — no `export`, no python-dotenv. See `.env.example`.

---

## 👥 Account management (admin API)

Protected by `BRIDGE_ADMIN_KEY` (set in `.env`). All admin calls require `Authorization: Bearer <admin_key>`.

### Create an account

```bash
curl -X POST http://127.0.0.1:52847/admin/accounts \
  -H "Authorization: Bearer <admin_key>" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-my-new-account", "label": "My New Account"}'
```

Response: `{"ok": true, "api_key": "sk-my-new-account"}`

### Start OAuth login for the new account

```bash
curl -X POST http://127.0.0.1:52847/admin/accounts/sk-my-new-account/login \
  -H "Authorization: Bearer <admin_key>"
```

Returns an `auth_url` — open it in your browser, authorize Google, and the bridge captures the code automatically (localhost callback). Or use manual mode:

```bash
# After authorizing in browser, copy the redirect URL and:
curl -X POST http://127.0.0.1:52847/auth/login/manual \
  -H "Content-Type: application/json" \
  -d '{"code": "..."}'
```

### List all accounts

```bash
curl http://127.0.0.1:52847/admin/accounts \
  -H "Authorization: Bearer <admin_key>"
```

### Remove an account

```bash
curl -X DELETE http://127.0.0.1:52847/admin/accounts/sk-my-new-account \
  -H "Authorization: Bearer <admin_key>"
```

### Use the account

```bash
curl http://127.0.0.1:52847/v1/chat/completions \
  -H "Authorization: Bearer sk-my-new-account" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash-low","messages":[{"role":"user","content":"hello"}]}'
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

### Interactive (standalone, no server needed)

```bash
python3 auth-login.py                      # single-account: writes BRIDGE_REFRESH_TOKEN into .env
python3 auth-login.py --bridge http://127.0.0.1:52847 --account sk-xxx   # multi-account, via a running bridge
```

Prints a Google link (PKCE), you authorize, paste the redirect URL (`localhost:51121` fails in the browser — that's fine, copy the URL).
Needs `ANTIGRAVITY_CLIENT_ID/SECRET` in `.env`.

### Web UI

Open `http://YOUR_HOST:PORT/login` in your browser — dual mode (auto callback + manual code paste).

### Manual (remote servers)

```bash
# 1. Get auth URL
curl -X POST http://YOUR_HOST:52847/auth/login

# 2. Open the returned auth_url in a browser, authorize

# 3. Copy the redirect URL and exchange:
curl -X POST http://YOUR_HOST:52847/auth/login/manual \
  -H "Content-Type: application/json" \
  -d '{"code": "PASTE_FULL_REDIRECT_URL_HERE"}'
```

---

## 🤖 Agent setup

### Hermes

```bash
./scripts/add-to-hermes.sh gemini-3.8-flash-low antigravity-bridge
```

### LiteLLM

Register the bridge as an `openai/` provider. Effort goes in the model id (or via `reasoning_effort`); native tools via
`web_search_options` (LiteLLM passes it through) or extra params.

```yaml
model_list:
  - model_name: gemini-3.8-flash          # what your apps call
    litellm_params:
      model: openai/gemini-3.8-flash-low  # bridge id (effort baked in)
      api_base: http://127.0.0.1:52847/v1
      api_key: sk-your-bridge-key         # BRIDGE_API_KEY or an accounts.json key
  - model_name: gemini-3.8-flash-high
    litellm_params:
      model: openai/gemini-3.8-flash-high
      api_base: http://127.0.0.1:52847/v1
      api_key: sk-your-bridge-key
  - model_name: claude-opus-via-google
    litellm_params:
      model: openai/claude-opus-4-6-thinking
      api_base: http://127.0.0.1:52847/v1
      api_key: sk-your-bridge-key
```

Works with `stream`, `tools`/`tool_choice`, vision, `response_format`, `reasoning_effort`, `user`.
LiteLLM's `drop_params` is not needed: unsupported params are ignored by the bridge with a log warning.
For grounding from LiteLLM: `extra_body: {"web_search": true}` (or `web_search_options: {}`).

### Open WebUI

1. Admin Panel → Settings → Connections → Add OpenAI API.
2. URL: `http://YOUR_SERVER:52847/v1`
3. Key: your account API key (from `accounts.json`).

### Generic OpenAI client

| Field | Value |
|-------|-------|
| Base URL | `http://YOUR_SERVER:52847/v1` |
| API key | Account key (`sk-...`) from `accounts.json` |
| Models | Fetched via `GET /v1/models` |

---

## 🆕 `dev` branch — Sep 2026

- **Antigravity CLI 1.1.28 protocol** (`daily-cloudcode-pa`, CLI User-Agent, `agent` request body, `aicode` scope). See `docs/agy-cli-protocol.md`.
- **Docs**: Swagger UI at `/docs`, OpenAPI 3.1 at `/api/spec.yml` (`openapi.yaml`); `docs/api-reference.md` (parameters & mapping), `docs/agy-cli-protocol.md` (captured protocol), `docs/reverse-engineering.md` (how to re-capture when Google changes something).
- **Native backend tools**: `web_search` (Google grounding with `citations`), `url_context`, `code_execution` (sandbox), image output (`gemini-3.1-flash-image`). Enable via `tools:[{type:...}]` or body flags.
- **Real Google quota per account**: `GET /v1/quota`, `GET /admin/accounts/<key>/quota`, `GET /admin/accounts?quota=1`.
- **Multimodal input**: `image_url`, `input_audio`, `file` (PDF/text/video/audio), `video_url`/`audio_url` → `inlineData`.
- `/v1/models` with real metadata (context window, max output, modalities, thinking); real `thinkingBudget` + `model_enum` from the catalog. `?cli=1` = the 14 `agy models` entries.
- `reasoning_effort` → model suffix; `user` → deterministic sessionId (no server-side memory).
- **Login**: `auth-login.py` is standalone (PKCE, no server needed) and writes `BRIDGE_REFRESH_TOKEN` into `.env`; `--bridge URL --account KEY` for multi-account.
- First run: `/auth/login` creates the default account (used to 500); `/health` returns `no_account`/`needs_login`.
- `server.py` loads `.env` by itself. `BRIDGE_DEBUG=1` → tracebacks + upstream request log.
- `ANTIGRAVITY_CLIENT_ID/SECRET` live in `.env` (GitHub blocks commits containing them); `install.sh` asks for them and preserves your existing `.env`.

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
BASE=http://127.0.0.1:52847

# Health
curl -s "$BASE/health" | jq

# Models
curl -s "$BASE/v1/models" | jq '.data[].id'

# Chat (no key, single-account mode)
curl -s "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash-low","messages":[{"role":"user","content":"hi"}]}' | jq

# Chat (with account key, multi-account mode)
curl -s "$BASE/v1/chat/completions" \
  -H "Authorization: Bearer sk-your-account" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"hi"}]}' | jq

# Streaming
curl -N "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash-low","stream":true,"messages":[{"role":"user","content":"tell me a joke"}]}'

# Usage
curl -s "$BASE/v1/usage" | jq

# Vision (image URL)
curl -s "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash-low","messages":[{"role":"user","content":[{"type":"text","text":"What do you see?"},{"type":"image_url","image_url":{"url":"https://example.com/photo.jpg"}}]}]}' | jq
```

---

## 🔒 Security

See `docs/security.md`. Short version: set `BRIDGE_API_KEY` (or accounts) **and** `BRIDGE_ADMIN_KEY`, bind `127.0.0.1`
or use a tailnet/TLS proxy, keep `BRIDGE_DEBUG=0`. Client-supplied URLs are SSRF-guarded (private ranges blocked).

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Bridge fails to start | Run manually with `BRIDGE_DEBUG=1 .venv/bin/python3 server.py` and read the traceback |
| `401 UNAUTHENTICATED` from Google | Refresh token without the `aicode` scope (pre-Sep-2026) or stale. Re-run `python3 auth-login.py`. Check: `curl "https://oauth2.googleapis.com/tokeninfo?access_token=<token>"` must list `auth/aicode` |
| `/auth/login` → `CLIENT_ID/SECRET are empty` | Put `ANTIGRAVITY_CLIENT_ID/SECRET` in `.env` (see Quick install) |
| `400 INVALID_ARGUMENT` on chat | Google changed the request shape. Follow `docs/reverse-engineering.md` to re-capture and diff |
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
