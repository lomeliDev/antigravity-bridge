# Antigravity Bridge — referencia de API y parámetros

Rama `dev` · sep 2026 · protocolo Antigravity CLI 1.1.28. Todo lo marcado ✅ está verificado en vivo.

## 1. Autenticación del cliente

| Header | Uso |
|---|---|
| `Authorization: Bearer <api_key>` | Selecciona la **cuenta Google** en `accounts.json`. En single-account (una sola cuenta, sin `BRIDGE_API_KEY`) se puede omitir. |
| `Authorization: Bearer <admin_key>` | Solo para `/admin/*` (si `BRIDGE_ADMIN_KEY` está definido). |
| `X-Session-Id: <id>` | Opcional. Igual que el campo `user` del body (ver §3). |

Cada api_key = una cuenta Google = su propia quota, su propio token cache. Las requests de una key **nunca** tocan otra cuenta.

## 2. `POST /v1/chat/completions` — formato OpenAI

```json
{
  "model": "gemini-3.8-flash-low",
  "messages": [...],
  "stream": false,
  "tools": [...], "tool_choice": "auto",
  "temperature": 1.0, "top_p": 0.95, "max_tokens": 8192,
  "reasoning_effort": "low",
  "response_format": {"type": "json_object"},
  "user": "cliente-123"
}
```

### 2.1 `model`

- IDs del catálogo (`GET /v1/models`). Los Gemini traen el **effort horneado**: `gemini-3.8-flash-low|medium|high`. Claude y GPT no tienen sufijo.
- `models/` como prefijo se tolera y se quita.
- **`reasoning_effort`** (`low|medium|high`, estándar OpenAI): si mandas `gemini-3.8-flash` sin sufijo, el bridge compone `gemini-3.8-flash-<effort>`; si mandas con sufijo Y `reasoning_effort`, gana `reasoning_effort`. Claude/GPT lo ignoran. ✅
- `?cli=1` en `/v1/models` filtra a los 14 que muestra `agy models`.

### 2.2 `messages` → Gemini `contents`

| OpenAI | Gemini (lo que se manda) |
|---|---|
| `system` (string o parts texto) | `systemInstruction: {role:"user", parts:[{text}]}` — se concatenan todos los system |
| `user` string | `{role:"user", parts:[{text}]}` |
| `user` con parts | ver §2.3 |
| `assistant` texto | `{role:"model", parts:[{text}]}` |
| `assistant` con `tool_calls` | `{role:"model", parts:[{thought:true,text,thoughtSignature}, {functionCall:{name,args,id}}, ...]}` — el primer functionCall lleva `thoughtSignature`, los paralelos no (requisito del API). En Claude no se inyecta signature. ✅ |
| `tool` (`tool_call_id`, `content`) | `{role:"user", parts:[{functionResponse:{name,id,response}}]}` — `content` JSON se parsea; texto plano va como `{result: "..."}` ✅ |
| `function` (legacy) | igual que `tool` sin id |

Multi-turno completo verificado: user → assistant(tool_calls) → tool → respuesta natural. ✅

### 2.3 Content parts (mensajes `user`)

| `type` | Formato | Se manda como |
|---|---|---|
| `text` | `{"type":"text","text":"..."}` | `{text}` |
| `image_url` | `{"image_url":{"url":"https://..."}}` o data-URI `data:image/png;base64,...` | `{inlineData:{mimeType,data}}` (el bridge descarga la URL) ✅ |
| `input_audio` | `{"input_audio":{"data":"<b64>","format":"wav\|mp3\|m4a\|ogg\|flac\|webm\|pcm16"}}` | `inlineData audio/*` |
| `file` | `{"file":{"file_data":"data:application/pdf;base64,...","filename":"x.pdf"}}` o `{"file":{"file_url":"https://..."}}` | `inlineData` (pdf, texto, video, audio; mime por header o extensión; máx 50 MB) |
| `video_url` / `audio_url` | `{"video_url":{"url":"..."}}` (extensión no estándar) | `inlineData` |

Modalidades soportadas por modelo: ver `supportedMimeTypes` en `GET /admin/models/raw`. Gemini: imagen, pdf, audio, video, texto. Claude vía Antigravity: solo imagen. GPT-OSS: solo texto.

### 2.4 Parámetros de generación

| OpenAI | Gemini `generationConfig` | Notas |
|---|---|---|
| `temperature` | `temperature` | default 1.0 |
| `top_p` | `topP` | default 0.95 |
| `max_tokens` / `max_completion_tokens` | `maxOutputTokens` | default 8192, capado por modelo |
| `n` | `candidateCount` | máx 8 |
| `seed` | `seed` | |
| `stop` (string o lista) | `stopSequences` | |
| `response_format` `json_object` / `json_schema` | `responseMimeType: application/json` (+ `responseSchema`) | |
| `reasoning_effort` | → sufijo del modelo | el budget sale del catálogo (ver abajo) |
| (automático) | `thinkingConfig.thinkingBudget` | **valor real por modelo** desde `fetchAvailableModels.thinkingBudget` (`-1` = dinámico en los Gemini `-high`; `1024` fijo en Claude); fallback tabla `AGY_THINKING_BUDGET` |
| (automático) | `labels.model_enum` | desde el catálogo (`MODEL_PLACEHOLDER_Mxx`) |
| (automático) | `maxOutputTokens` cap | se capa al `maxOutputTokens` real del modelo |
| `thinking_budget` (extra) | `thinkingConfig.thinkingBudget` | fuerza el budget exacto |
| `include_thoughts` (extra) | `thinkingConfig.includeThoughts` | default false |
| `stream` | endpoint `:streamGenerateContent?alt=sse` vs `:generateContent` | ✅ ambos |
| `stream_options.include_usage` | chunk final con `usage` | |
| `logprobs`, `frequency_penalty`, `presence_penalty`, `logit_bias`, `top_logprobs` | — | **ignorados** con warning en log |

### 2.5 `tools` / `tool_choice`

- `tools[].function.{name,description,parameters}` → `tools[0].functionDeclarations[]`. El schema JSON se limpia de campos que Gemini rechaza (`$schema`, `additionalProperties`, `default`, formatos no soportados, etc.).
- `tool_choice`: `auto` → `AUTO`, `none` → `NONE`, `required`/objeto → `ANY` (en Claude vía Antigravity solo `AUTO`/`ANY`).
- Respuesta: `functionCall` → `tool_calls[{id, type:"function", function:{name, arguments(JSON string)}}]`, `finish_reason: "tool_calls"`. IDs se preservan entre turnos. ✅
- Parallel tool calls: N `functionCall` parts → N `tool_calls` en el mismo mensaje.

### 2.5b Tools nativas del backend (verificadas ✅)

El backend de Antigravity acepta las tools nativas de Gemini aunque agy no las exponga. Se activan con vocabulario OpenAI o flags:

| Activación (cualquiera) | Tool Gemini | Qué hace |
|---|---|---|
| `tools:[{"type":"web_search"}]` · `{"type":"web_search_preview"}` · `"web_search": true` · `"web_search_options": {}` | `googleSearch` | **Grounding con Google Search** — respuestas con datos actuales. El message trae `citations:[{url,title}]` y `search_queries` |
| `tools:[{"type":"url_context"}]` · `"url_context": true` | `urlContext` | El modelo lee las URLs que aparezcan en el prompt |
| `tools:[{"type":"code_execution"}]` · `{"type":"code_interpreter"}` · `"code_execution": true` | `codeExecution` | Ejecuta Python en el sandbox de Google; el código y su salida se renderizan como bloques markdown en `content` |

Se pueden combinar con `function` tools en la misma request. Ejemplo:

```json
{"model":"gemini-3.8-flash-low","web_search":true,
 "messages":[{"role":"user","content":"ultima version de opencode?"}]}
```

Imágenes generadas (modelos `*-image` con `responseModalities`): llegan como `![image](data:image/png;base64,...)` en `content` y además en `images:[{mime_type,b64_json}]`.

No disponible en este backend: `embedContent` (404). `countTokens` existe pero con otro shape (pendiente).

### 2.6 `user` / sesiones

- **No hay memoria server-side**: cada request es stateless; la conversación va completa en `messages`. Nada se comparte entre api_keys ni entre `user`s.
- `user` (OpenAI) o header `X-Session-Id`: genera `sessionId` y `conversation_id` **deterministas** (sha256 de `api_key:user`) → Google agrupa la actividad de ese usuario y mejora el cache de prompt (`cachedContentTokenCount`). Sin `user`, cada request es sesión nueva aleatoria.

## 3. Lo que realmente viaja a Google (por request)

```
POST https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse
Authorization: Bearer <access_token de la cuenta>
User-Agent: antigravity/cli/1.1.28 (aidev_client; os_type=linux; arch=amd64; cl=978129418; auth_method=consumer)
Content-Type: application/json

{
  "project": "aicode-consumers",
  "requestId": "agent/<conversation_id>/<epoch_ms>/<trajectory_id>/1",
  "model": "<model_id resuelto>",
  "userAgent": "antigravity",
  "requestType": "agent",
  "request": {
    "contents": [...], "systemInstruction": {...}, "tools": [...], "toolConfig": {...},
    "generationConfig": {...},
    "sessionId": "<int64>",
    "labels": {"last_step_index":"0","request_id":"<traj>-0","trajectory_id":"<traj>",
               "used_claude":"true|false","used_claude_conservative":"false","used_non_gemini_model":"true|false"}
  }
}
```

Diferencia con el CLI: **sin** el system prompt de ~13k tokens ni las 50+ tools de agy → un "hola" cuesta ~10 tokens en vez de 13k. Mismo backend, misma quota, misma cuenta.

## 4. Respuesta

Formato OpenAI estándar: `id`, `object`, `created`, `model` (el resuelto), `choices[].message|delta`, `finish_reason` (`stop`/`tool_calls`/`length`), `usage{prompt_tokens, completion_tokens, total_tokens}`. En streaming: chunks `data: {...}` + `data: [DONE]`. `total_tokens` incluye thinking cuando el modelo razona (por eso puede ser > prompt+completion).

## 5. Endpoints

| Método | Ruta | Auth | Qué |
|---|---|---|---|
| GET | `/` | — | info + lista de endpoints |
| GET | `/health` | — | `ok` / `needs_login` / `no_account` (nunca 500) |
| GET | `/v1/models` (`?cli=1`) | — | catálogo (`fetchAvailableModels`, cache 1h) |
| GET | `/v1/models/<id>` | — | un modelo |
| POST | `/v1/chat/completions` | key | chat, stream, tools, multimodal |
| GET | `/v1/usage` | — | contadores locales por modelo (desde el arranque) |
| GET | `/v1/quota` (`?refresh=1`) | key | **quota real de Google** de la cuenta del request |
| GET | `/v1/billing/subscription` | — | stub (Hermes) |
| GET | `/admin/accounts` (`?quota=1`) | admin | lista; con quota real por cuenta |
| POST | `/admin/accounts` | admin | crear `{api_key,label}` |
| DELETE | `/admin/accounts/<key>` | admin | borrar |
| POST | `/admin/accounts/<key>/login` | admin | inicia OAuth → `auth_url` |
| GET | `/admin/accounts/<key>/quota` | admin | 4 buckets con % usado y reset |
| GET | `/admin/models/raw` | admin | `fetchAvailableModels` crudo |
| POST | `/auth/login` · `/auth/login/manual` · `/auth/login/callback` · GET `/auth/login/status` · `/login` | — | OAuth de la cuenta default / web UI |

### Quota (`/v1/quota`, `/admin/accounts/<key>/quota`)

```json
{"email":"...","label":"...","project":"aicode-consumers",
 "buckets":{"gemini-weekly":{"group":"Gemini Models","window":"weekly","used_pct":0.1,"remaining_pct":99.9,"reset_at":"..."},
            "gemini-5h":{...},"3p-weekly":{...},"3p-5h":{...}},
 "gemini_weekly_used":0.1,"gemini_5h_used":1.0,"claude_weekly_used":2.8,"claude_5h_used":2.3,"fetched_at":1788980000}
```
Gemini Flash/Pro comparten los buckets `gemini-*`; Claude y GPT-OSS comparten `3p-*`. Cache 30 s (`BRIDGE_QUOTA_TTL`).

## 6. Variables de entorno (`.env`, lo carga `server.py`)

| Var | Default | Qué |
|---|---|---|
| `HOST` / `PORT` | 0.0.0.0 / 52847 | |
| `BRIDGE_DEBUG` | 0 | tracebacks + body upstream en log |
| `ANTIGRAVITY_CLIENT_ID` / `_SECRET` | (vacío) | **obligatorios**; client OAuth de Antigravity (van en .env, no en repo) |
| `BRIDGE_REFRESH_TOKEN` | | single-account |
| `BRIDGE_API_KEY` | | key de cliente en single-account |
| `BRIDGE_ADMIN_KEY` | | protege `/admin/*` |
| `BRIDGE_ACCOUNTS_FILE` / `BRIDGE_AUTH_CACHE_DIR` | ./accounts.json / ./auth_cache | multi-account |
| `ANTIGRAVITY_ASSIST_URL` | daily-cloudcode-pa…/v1internal | backend |
| `AGY_CLI_VERSION` / `AGY_CLI_CL` / `AGY_AUTH_METHOD` | 1.1.28 / 978129418 / consumer | User-Agent |
| `AGY_CONSUMER_PROJECT` | aicode-consumers | fallback de `project` |
| `BRIDGE_QUOTA_TTL` | 30 | cache de quota (s) |

### `/v1/models` — metadata por modelo

Cada entrada trae, además de `id`/`owned_by`: `display_name`, `context_window` (1M en Gemini 3.x Flash, 250k en Claude), `max_output_tokens`, `supports_thinking/images/video`, `input_modalities` (`text/image/audio/video/application`), `web_search` (el backend marca qué modelos soportan búsqueda), `image_generation`, `deprecated`, `effort`. `GET /v1/models/<id>` agrega `metadata` completa (mime types, enum, vertex id, budgets).

## 7. Pendientes conocidos

- Salida de imagen/audio (modelos `*-image`, tts): no mapeada al formato OpenAI.
- Features del backend por sondear (Bloque C): `googleSearch`, `urlContext`, `codeExecution`, `responseModalities: IMAGE`, `:countTokens`, `:embedContent`.
- `/auth/login/manual` opera sobre la última cuenta que inició login; en multi-cuenta hacer logins en serie.
