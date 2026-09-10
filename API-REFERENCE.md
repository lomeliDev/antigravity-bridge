# Antigravity Bridge — API & parameter reference

Branch `dev` · Sep 2026 · Antigravity CLI 1.1.28 protocol. Everything marked ✅ was verified live.
Interactive docs: `GET /docs` (Swagger UI) · machine spec: `GET /api/spec.yml` (`openapi.yaml`).

## 1. Client authentication

| Header | Use |
|---|---|
| `Authorization: Bearer <api_key>` | Selects the **Google account** in `accounts.json`. In single-account mode (one account, no `BRIDGE_API_KEY`) it can be omitted. |
| `Authorization: Bearer <admin_key>` | Only for `/admin/*` (when `BRIDGE_ADMIN_KEY` is set). |
| `X-Session-Id: <id>` | Optional. Same as the `user` body field (see §2.6). |

Each api_key = one Google account = its own quota and token cache. Requests for one key **never** touch another account.

## 2. `POST /v1/chat/completions` — OpenAI format

```json
{
  "model": "gemini-3.8-flash-low",
  "messages": [...],
  "stream": false,
  "tools": [...], "tool_choice": "auto",
  "temperature": 1.0, "top_p": 0.95, "max_tokens": 8192,
  "reasoning_effort": "low",
  "response_format": {"type": "json_object"},
  "user": "customer-123"
}
```

### 2.1 `model`

- Catalog IDs (`GET /v1/models`). Gemini models carry the **effort in the id**: `gemini-3.8-flash-low|medium|high`. Claude and GPT have no suffix.
- A `models/` prefix is tolerated and stripped.
- **`reasoning_effort`** (`low|medium|high`, standard OpenAI): if you send `gemini-3.8-flash` without suffix, the bridge composes `gemini-3.8-flash-<effort>`; if you send a suffix AND `reasoning_effort`, `reasoning_effort` wins. Ignored for Claude/GPT. ✅
- `?cli=1` on `/v1/models` filters to the 14 models shown by `agy models`.

### 2.2 `messages` → Gemini `contents`

| OpenAI | Gemini (what is sent) |
|---|---|
| `system` (string or text parts) | `systemInstruction: {role:"user", parts:[{text}]}` — all system messages are concatenated |
| `user` string | `{role:"user", parts:[{text}]}` |
| `user` with parts | see §2.3 |
| `assistant` text | `{role:"model", parts:[{text}]}` |
| `assistant` with `tool_calls` | `{role:"model", parts:[{thought:true,text,thoughtSignature}, {functionCall:{name,args,id}}, ...]}` — the first functionCall carries the `thoughtSignature`, parallel ones don't (API requirement). Not injected for Claude. ✅ |
| `tool` (`tool_call_id`, `content`) | `{role:"user", parts:[{functionResponse:{name,id,response}}]}` — JSON `content` is parsed; plain text goes as `{result: "..."}` ✅ |
| `function` (legacy) | same as `tool` without id |

Full multi-turn verified: user → assistant(tool_calls) → tool → natural-language answer. ✅

### 2.3 Content parts (`user` messages)

| `type` | Format | Sent as |
|---|---|---|
| `text` | `{"type":"text","text":"..."}` | `{text}` |
| `image_url` | `{"image_url":{"url":"https://..."}}` or data URI `data:image/png;base64,...` | `{inlineData:{mimeType,data}}` (the bridge downloads the URL) ✅ |
| `input_audio` | `{"input_audio":{"data":"<b64>","format":"wav\|mp3\|m4a\|ogg\|flac\|webm\|pcm16"}}` | `inlineData audio/*` |
| `file` | `{"file":{"file_data":"data:application/pdf;base64,...","filename":"x.pdf"}}` or `{"file":{"file_url":"https://..."}}` | `inlineData` (pdf, text, video, audio; mime from header or extension; max 50 MB) |
| `video_url` / `audio_url` | `{"video_url":{"url":"..."}}` (non-standard extension) | `inlineData` |

Modalities supported per model: see `supportedMimeTypes` in `GET /v1/models/<id>` (`metadata`). Gemini: image, pdf, audio, video, text. Claude via Antigravity: image only. GPT-OSS: text only.

### 2.4 Generation parameters

| OpenAI | Gemini `generationConfig` | Notes |
|---|---|---|
| `temperature` | `temperature` | default 1.0 |
| `top_p` | `topP` | default 0.95 |
| `max_tokens` / `max_completion_tokens` | `maxOutputTokens` | default 8192, capped to the model's `max_output_tokens` |
| `n` | `candidateCount` | max 8 |
| `seed` | `seed` | |
| `stop` (string or list) | `stopSequences` | |
| `response_format` `json_object` / `json_schema` | `responseMimeType: application/json` (+ `responseSchema`) | |
| `reasoning_effort` | → model suffix | the budget comes from the catalog (below) |
| (automatic) | `thinkingConfig.thinkingBudget` | **real per-model value** from `fetchAvailableModels.thinkingBudget` (`-1` = dynamic on Gemini `-high`; `1024` fixed on Claude); fallback table `AGY_THINKING_BUDGET` |
| `thinking_budget` (extension) | `thinkingConfig.thinkingBudget` | forces an exact budget |
| `include_thoughts` (extension) | `thinkingConfig.includeThoughts` | default false |
| (automatic) | `labels.model_enum` | from the catalog (`MODEL_PLACEHOLDER_Mxx`) |
| `stream` | `:streamGenerateContent?alt=sse` vs `:generateContent` | ✅ both |
| `stream_options.include_usage` | final chunk with `usage` | |
| `logprobs`, `frequency_penalty`, `presence_penalty`, `logit_bias`, `top_logprobs` | — | **ignored** with a log warning |

### 2.5 `tools` / `tool_choice` (function calling)

- `tools[].function.{name,description,parameters}` → `tools[].functionDeclarations[]`. The JSON Schema is stripped of fields Gemini rejects (`$schema`, `additionalProperties`, `default`, unsupported formats, etc.).
- `tool_choice`: `auto` → `AUTO`, `none` → `NONE`, `required`/object → `ANY` (Claude via Antigravity only `AUTO`/`ANY`).
- Response: `functionCall` → `tool_calls[{id, type:"function", function:{name, arguments(JSON string)}}]`, `finish_reason: "tool_calls"`. IDs are preserved across turns. ✅
- Parallel tool calls: N `functionCall` parts → N `tool_calls` in the same message.

### 2.5b Native backend tools (verified ✅)

The Antigravity backend accepts Gemini's native tools even though agy doesn't expose them. Enable with OpenAI vocabulary or flags:

| Enable with (any) | Gemini tool | What it does |
|---|---|---|
| `tools:[{"type":"web_search"}]` · `{"type":"web_search_preview"}` · `"web_search": true` · `"web_search_options": {}` | `googleSearch` | **Google Search grounding** — answers with current data. The message carries `citations:[{url,title}]` and `search_queries` |
| `tools:[{"type":"url_context"}]` · `"url_context": true` | `urlContext` | The model reads URLs present in the prompt |
| `tools:[{"type":"code_execution"}]` · `{"type":"code_interpreter"}` · `"code_execution": true` | `codeExecution` | Runs Python in Google's sandbox; the code and its output are rendered as markdown blocks in `content` |

They can be combined with `function` tools in the same request. Example:

```json
{"model":"gemini-3.8-flash-low","web_search":true,
 "messages":[{"role":"user","content":"latest opencode version?"}]}
```

All three verified live through the bridge (grounding with 6 citations, urlContext reading opencode.ai, codeExecution summing primes = 76127). Citations arrive as `vertexaisearch.cloud.google.com/grounding-api-redirect/...` redirects (they open the real site); with `BRIDGE_RESOLVE_CITATIONS=1` the bridge resolves them to the final URL (HEAD, ~200 ms/citation, cached).

**Generated images** (`gemini-3.1-flash-image`) ✅: returned as `![image](data:image/jpeg;base64,...)` in `content` and also in `images:[{mime_type,b64_json}]`. No `responseModalities` needed.

Not available on this backend: `embedContent` (404). `countTokens` exists but with a different shape (pending).

### 2.6 `user` / sessions

- **No server-side memory**: every request is stateless; the whole conversation travels in `messages`. Nothing is shared across api_keys or `user`s.
- `user` (OpenAI) or header `X-Session-Id`: derives **deterministic** `sessionId` and `conversation_id` (sha256 of `api_key:user`) → Google groups that user's activity and prompt caching (`cachedContentTokenCount`) hits more often. Without `user`, every request is a fresh random session.

## 3. What actually goes to Google (per request)

```
POST https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse
Authorization: Bearer <account access_token>
User-Agent: antigravity/cli/1.1.28 (aidev_client; os_type=linux; arch=amd64; cl=978129418; auth_method=consumer)
Content-Type: application/json

{
  "project": "aicode-consumers",
  "requestId": "agent/<conversation_id>/<epoch_ms>/<trajectory_id>/1",
  "model": "<resolved model_id>",
  "userAgent": "antigravity",
  "requestType": "agent",
  "request": {
    "contents": [...], "systemInstruction": {...}, "tools": [...], "toolConfig": {...},
    "generationConfig": {...},
    "sessionId": "<int64>",
    "labels": {"last_step_index":"0","model_enum":"MODEL_PLACEHOLDER_Mxx","request_id":"<traj>-0","trajectory_id":"<traj>",
               "used_claude":"true|false","used_claude_conservative":"false","used_non_gemini_model":"true|false"}
  }
}
```

Difference vs the CLI: **no** ~13k-token system prompt and none of agy's 50+ tools → a "hello" costs ~10 tokens instead of 13k. Same backend, same quota, same account.

## 4. Response

Standard OpenAI format: `id`, `object`, `created`, `model` (resolved), `choices[].message|delta`, `finish_reason` (`stop`/`tool_calls`/`length`), `usage{prompt_tokens, completion_tokens, total_tokens}`. Streaming: `data: {...}` chunks + `data: [DONE]`. `total_tokens` includes thinking when the model reasons (so it can exceed prompt+completion). Extensions in `message`: `citations`, `search_queries`, `images`.

## 5. Endpoints

| Method | Path | Auth | What |
|---|---|---|---|
| GET | `/` | — | info + endpoint list |
| GET | `/health` | — | `ok` / `needs_login` / `no_account` (never 500) |
| GET | `/docs` · `/api/spec.yml` | — | Swagger UI · OpenAPI 3.1 |
| GET | `/v1/models` (`?cli=1`) | — | catalog with metadata (`fetchAvailableModels`, 1h cache) |
| GET | `/v1/models/<id>` | — | one model + full `metadata` |
| POST | `/v1/chat/completions` | key | chat, stream, tools, multimodal, native tools |
| GET | `/v1/usage` | — | local per-model counters (since startup) |
| GET | `/v1/quota` (`?refresh=1`) | key | **real Google quota** for the request's account |
| GET | `/v1/billing/subscription` | — | stub (Hermes) |
| GET | `/admin/accounts` (`?quota=1`) | admin | list; with real quota per account |
| POST | `/admin/accounts` | admin | create `{api_key,label[,refresh_token]}` |
| DELETE | `/admin/accounts/<key>` | admin | delete |
| POST | `/admin/accounts/<key>/login` | admin | start OAuth → `auth_url` |
| GET | `/admin/accounts/<key>/quota` | admin | 4 buckets with used % and reset |
| GET | `/admin/models/raw` | admin | raw `fetchAvailableModels` |
| POST | `/auth/login` · `/auth/login/manual` · `/auth/login/callback` · GET `/auth/login/status` · `/login` | — | OAuth for the default account / web UI |

### Quota (`/v1/quota`, `/admin/accounts/<key>/quota`)

```json
{"email":"...","label":"...","project":"aicode-consumers",
 "buckets":{"gemini-weekly":{"group":"Gemini Models","window":"weekly","used_pct":0.1,"remaining_pct":99.9,"reset_at":"..."},
            "gemini-5h":{...},"3p-weekly":{...},"3p-5h":{...}},
 "gemini_weekly_used":0.1,"gemini_5h_used":1.0,"claude_weekly_used":2.8,"claude_5h_used":2.3,"fetched_at":1788980000}
```
Gemini Flash/Pro share the `gemini-*` buckets; Claude and GPT-OSS share `3p-*`. 30 s cache (`BRIDGE_QUOTA_TTL`).

### `/v1/models` — per-model metadata

Each entry has, besides `id`/`owned_by`: `display_name`, `context_window` (1M on Gemini 3.x Flash, 250k on Claude), `max_output_tokens`, `supports_thinking/images/video`, `input_modalities` (`text/image/audio/video/application`), `web_search` (backend marks which models support search), `image_generation`, `deprecated`, `effort`. `GET /v1/models/<id>` adds full `metadata` (mime types, enum, vertex id, budgets).

## 6. Environment variables (`.env`, loaded by `server.py` itself)

| Var | Default | What |
|---|---|---|
| `HOST` / `PORT` | 0.0.0.0 / 52847 | |
| `BRIDGE_DEBUG` | 0 | full tracebacks + upstream request bodies in the log (contains base64 images — keep 0 in prod) |
| `ANTIGRAVITY_CLIENT_ID` / `_SECRET` | (empty) | **required**; Antigravity's OAuth client (in .env, never in the repo) |
| `BRIDGE_REFRESH_TOKEN` | | single-account |
| `BRIDGE_API_KEY` | | client key in single-account mode |
| `BRIDGE_ADMIN_KEY` | | protects `/admin/*` |
| `BRIDGE_ACCOUNTS_FILE` / `BRIDGE_AUTH_CACHE_DIR` | ./accounts.json / ./auth_cache | multi-account |
| `ANTIGRAVITY_ASSIST_URL` | daily-cloudcode-pa…/v1internal | backend |
| `AGY_CLI_VERSION` / `AGY_CLI_CL` / `AGY_AUTH_METHOD` | 1.1.28 / 978129418 / consumer | User-Agent |
| `AGY_CONSUMER_PROJECT` | aicode-consumers | `project` fallback |
| `BRIDGE_QUOTA_TTL` | 30 | quota cache (s) |
| `BRIDGE_RESOLVE_CITATIONS` | 0 | resolve grounding citation redirects to the real URL |

## 7. Login

- **Standalone** (no server needed): `python3 auth-login.py` — PKCE flow, writes `BRIDGE_REFRESH_TOKEN` into `.env` preserving everything else. Needs `ANTIGRAVITY_CLIENT_ID/SECRET` in `.env`.
- **Through a running bridge** (multi-account): `python3 auth-login.py --bridge http://127.0.0.1:52847 --account sk-xxx [--admin-key ...]`.
- ⚠️ Refresh tokens created before Sep 2026 lack the `aicode` scope → 401 on the backend. Re-login.

## 8. Known gaps

- Image/audio **output** for `*-image` / tts models beyond the chat data-URI mapping (no `/v1/images/generations` yet).
- `countTokens` exists on the backend with a different body shape (not wired).
- `/auth/login/manual` acts on the last account that started a login; in multi-account, log in one at a time (or use `auth-login.py --bridge --account`).
- Audio/PDF input implemented but not exercised live yet.
