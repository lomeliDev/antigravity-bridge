<div align="center">

# Antigravity Bridge

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**English** | [Español](#español)

A tiny **OpenAI-compatible HTTP bridge** that wraps your **Antigravity / Gemini Code Assist** Google OAuth account, so clients like **Hermes**, **Open WebUI**, **Boba**, **BetterGPT**, etc. can use it.

</div>

---

## What is it?

Your Antigravity account is already authorized and stores valid tokens in `~/.local/share/opencode/auth.json`, but there is no standard OpenAI endpoint to consume it. This bridge closes that gap.

```text
┌──────────┐    OpenAI API    ┌────────────────────┐   HTTPS   ┌──────────────────────┐
│  Hermes  │ ───────────────► │ antigravity-bridge │ ────────► │ cloudcode-pa.google   │
│  WebUI   │   /v1/chat/...   │  Flask :PORT       │  Bearer   │ :loadCodeAssist      │
│  Boba    │                  │                    │  +project │ :generateContent     │
└──────────┘                  └────────────────────┘           │ :streamGenerateContent│
                                                               └──────────────────────┘
```

## Quick start

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

The installer will ask for a **port** and an optional **API key**, then render a systemd service file.

```bash
# Linux with systemd
sudo cp antigravity-bridge.service.rendered /etc/systemd/system/antigravity-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now antigravity-bridge
```

```bash
# macOS or Linux without systemd
source .env
.venv/bin/python3 server.py
```

## Configure Hermes / Open WebUI

| Field    | Value                                         |
|----------|-----------------------------------------------|
| Base URL | `http://YOUR_SERVER_IP:PORT/v1`               |
| API key  | `sk-local` or your `BRIDGE_API_KEY`           |
| Models   | Automatically fetched from `GET /v1/models`   |

## Supported OpenAI features

- `POST /v1/chat/completions` (blocking + SSE streaming)
- `GET /v1/models` and `GET /v1/models/{id}`
- Tool/functions (`tools`, `tool_choice`, multi-turn `role: "tool"`)
- Images in messages (`image_url` with base64 data URI or http(s) URL)
- `response_format` (`json_object` and `json_schema`)
- `seed`, `max_tokens`, `max_completion_tokens`, `n`, `stop`, `temperature`, `top_p`
- `stream_options.include_usage`
- Optional `BRIDGE_API_KEY` client authentication

## Configuration

| Variable              | Default                                                                 | Purpose                         |
|-----------------------|-------------------------------------------------------------------------|---------------------------------|
| `HOST`                | `127.0.0.1`                                                             | Listen host                     |
| `PORT`                | `8080`                                                                  | Listen port                     |
| `BRIDGE_API_KEY`      | *(none)*                                                                | Optional client API key         |
| `ANTIGRAVITY_CONST`   | `~/.cache/opencode/packages/opencode-antigravity-auth@latest/.../constants.js` | OAuth client credentials        |
| `ANTIGRAVITY_ACCOUNTS`| `~/.config/opencode/antigravity-accounts.json`                          | Account + refresh token         |
| `ANTIGRAVITY_AUTH`    | `~/.local/share/opencode/auth.json`                                     | Cached access token + projectId |

## Quick tests

```bash
# Health
curl -s http://127.0.0.1:8081/health | jq

# Models
curl -s http://127.0.0.1:8081/v1/models | jq '.data[].id'

# Chat
curl -s http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hello"}]}' | jq

# Streaming
curl -N http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","stream":true,"messages":[{"role":"user","content":"tell me a joke"}]}'
```

## Limitations

- `logprobs` / `top_logprobs` are not supported by the Antigravity upstream.
- `frequency_penalty`, `presence_penalty`, `logit_bias` are ignored.
- `n > 1` only works on models that allow multiple candidates.
- PDF/audio/video are not supported via the standard OpenAI chat-completion format.

---

<h1 id="español" align="center">Antigravity Bridge</h1>

<div align="center">

[English](#what-is-it) | **Español**

Un pequeño **bridge HTTP compatible con OpenAI** que envuelve tu cuenta de **Antigravity / Gemini Code Assist** con OAuth de Google, para que clientes como **Hermes**, **Open WebUI**, **Boba**, **BetterGPT**, etc. puedan usarla.

</div>

---

## ¿Qué es?

Tu cuenta de Antigravity ya está autorizada y guarda tokens válidos en `~/.local/share/opencode/auth.json`, pero no hay un endpoint estándar de OpenAI para consumirla. Este bridge cierra ese hueco.

## Inicio rápido

```bash
git clone https://github.com/lomeliDev/antigravity-bridge.git
cd antigravity-bridge
./install.sh
```

El instalador pedirá un **puerto** y una **API key** opcional, luego generará un archivo de servicio systemd.

```bash
# Linux con systemd
sudo cp antigravity-bridge.service.rendered /etc/systemd/system/antigravity-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now antigravity-bridge
```

```bash
# macOS o Linux sin systemd
source .env
.venv/bin/python3 server.py
```

## Configurar Hermes / Open WebUI

| Campo     | Valor                                          |
|-----------|------------------------------------------------|
| Base URL  | `http://IP_DE_TU_SERVIDOR:PUERTO/v1`           |
| API key   | `sk-local` o tu `BRIDGE_API_KEY`               |
| Modelos   | Se obtienen automáticamente de `GET /v1/models`|

## Características soportadas

- `POST /v1/chat/completions` (bloqueante + streaming SSE)
- `GET /v1/models` y `GET /v1/models/{id}`
- Tools/functions (`tools`, `tool_choice`, multi-turn `role: "tool"`)
- Imágenes en mensajes (`image_url` con data URI base64 o URL http(s))
- `response_format` (`json_object` y `json_schema`)
- `seed`, `max_tokens`, `max_completion_tokens`, `n`, `stop`, `temperature`, `top_p`
- `stream_options.include_usage`
- Autenticación opcional de clientes con `BRIDGE_API_KEY`

## Configuración

| Variable              | Valor por defecto                                                       | Propósito                       |
|-----------------------|-------------------------------------------------------------------------|---------------------------------|
| `HOST`                | `127.0.0.1`                                                             | Host de escucha                 |
| `PORT`                | `8080`                                                                  | Puerto de escucha               |
| `BRIDGE_API_KEY`      | *(ninguna)*                                                             | API key opcional para clientes  |
| `ANTIGRAVITY_CONST`   | `~/.cache/opencode/packages/opencode-antigravity-auth@latest/.../constants.js` | Credenciales OAuth              |
| `ANTIGRAVITY_ACCOUNTS`| `~/.config/opencode/antigravity-accounts.json`                          | Cuenta + refresh token          |
| `ANTIGRAVITY_AUTH`    | `~/.local/share/opencode/auth.json`                                     | Access token + projectId cache  |

## Tests rápidos

```bash
# Health
curl -s http://127.0.0.1:8081/health | jq

# Modelos
curl -s http://127.0.0.1:8081/v1/models | jq '.data[].id'

# Chat
curl -s http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hola"}]}' | jq

# Streaming
curl -N http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","stream":true,"messages":[{"role":"user","content":"cuentame un chiste"}]}'
```

## Limitaciones

- `logprobs` / `top_logprobs` no son soportados por el upstream de Antigravity.
- `frequency_penalty`, `presence_penalty`, `logit_bias` se ignoran.
- `n > 1` solo funciona en modelos que permiten múltiples candidatos.
- PDF/audio/video no son soportados por el formato estándar de chat completions de OpenAI.

## Licencia

MIT
