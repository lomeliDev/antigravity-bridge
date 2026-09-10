# Security notes

What the bridge protects, what it doesn't, and how to deploy it safely. Read this before exposing it beyond localhost.

## What is sensitive here

| Asset | Where | Protection |
|---|---|---|
| Google **refresh tokens** (= full access to the Google AI subscription of each account) | `.env` (`BRIDGE_REFRESH_TOKEN`), `accounts.json`, `auth_cache/*.json` | files written with mode `600`/`700`; never logged; never returned by any endpoint |
| OAuth **client id/secret** | `.env`, `accounts.json` | not in the repo (GitHub push-protection); `600` |
| Account **emails** | `/health`, `/v1/quota`, `/admin/accounts` | behind api_key / admin key |
| Your **quota** (someone else burning it) | `/v1/chat/completions` | behind api_key |

## Authentication layers

1. **Client → bridge**: `Authorization: Bearer <api_key>`. In multi-account mode each key maps to one Google account.
   In single-account mode with no `BRIDGE_API_KEY` set, **anyone who can reach the port can use your quota** —
   only acceptable on `127.0.0.1` or inside a tailnet/VPN.
2. **Admin**: `BRIDGE_ADMIN_KEY` protects `/admin/*` (list accounts + emails, create/delete accounts, start OAuth logins,
   raw model catalog). If unset, `/admin/*` is **open** — the server logs a warning at startup. `install.sh` now
   generates one by default. Keys are compared in constant time.
3. **Bridge → Google**: short-lived access tokens refreshed from the refresh token; scopes limited to what the CLI uses
   (`aicode`, `cloud-platform`, `cclog`, `experimentsandconfigs`, `userinfo.*`, `openid`).

## Network exposure

- Default bind is `0.0.0.0`. `install.sh` asks; choose `127.0.0.1` unless clients on other hosts need it.
- Recommended for remote access: **Tailscale / WireGuard**, or a reverse proxy with TLS (nginx/Caddy) in front —
  the bridge speaks plain HTTP and Flask's dev server (fine for a personal proxy, not for the public internet).
- If you must expose it: set `BRIDGE_API_KEY`/accounts + `BRIDGE_ADMIN_KEY`, put TLS in front, restrict by IP.

## SSRF guard (client-supplied URLs)

`image_url`, `file_url`, `video_url`, `audio_url` are fetched **by the bridge**. Without a guard a client could make it
request internal services: `http://127.0.0.1:<port>/admin/...` (this bridge), agy's local RPC, `169.254.169.254`
(cloud metadata), `10.x`/`192.168.x`. The bridge blocks non-http(s) schemes, `localhost`/`*.internal`/`*.local`,
and any hostname resolving to private, loopback, link-local, reserved or multicast ranges. Override with
`BRIDGE_ALLOW_PRIVATE_URLS=1` only if you trust every client. Sizes are capped (`BRIDGE_MAX_IMAGE_BYTES` 20 MB,
files 50 MB).

## Logging

- `BRIDGE_DEBUG=1` logs the **full upstream request body** (truncated to 4 KB) — that includes your prompts and
  base64 image data. Keep it `0` in production; logs go to journald (systemd) / `bridge.log` (launchd).
- Authorization headers and tokens are never logged.

## Prompt-injection surface

With `web_search` / `url_context` enabled, the model reads third-party web content. That content can contain
instructions. The bridge does not execute tool calls itself (function calls are returned to the client), but if
**your** client auto-executes tools, treat grounded/url-context responses as untrusted input.

## Google-side considerations

- This uses a consumer subscription (Google AI Pro/Ultra) through the Antigravity CLI's OAuth client. It is the same
  traffic the CLI generates, minus the CLI system prompt. Quota, rate limits and ToS are Google's.
- The User-Agent/`cl` fingerprint is configurable (`AGY_CLI_VERSION`, `AGY_CLI_CL`) — keep it in sync with the real
  CLI if Google starts rejecting old ones (`docs/reverse-engineering.md`).

## Checklist for a remote deployment

- [ ] `BRIDGE_API_KEY` or `accounts.json` with per-client keys
- [ ] `BRIDGE_ADMIN_KEY` set
- [ ] bind `127.0.0.1` + tailnet/TLS proxy, **or** firewall to known client IPs
- [ ] `BRIDGE_DEBUG=0`
- [ ] `.env`, `accounts.json`, `auth_cache/` owned by the service user, mode `600`/`700`
- [ ] GitHub token used for the repo revoked after use
