# Antigravity CLI → cloudcode-pa: protocolo capturado (mitmproxy, agy 1.1.28, 2026-09-08)

Capturado con `HTTPS_PROXY=http://127.0.0.1:8080 SSL_CERT_FILE=~/.mitmproxy/mitmproxy-ca-cert.pem` sobre un run stream-json de "responde unicamente con la palabra: OK" en `gemini-3.8-flash-low`. **agy no pinea certificados** — mitmproxy entra directo.

## 1. Hosts y secuencia de arranque

| Host | Para qué |
|---|---|
| `antigravity-unleash.goog` | feature flags (Unleash): `POST /api/client/register`, `GET /api/client/features` (71KB) |
| `playwright*.azureedge.net` | intenta bajar `playwright-1.57.0-linux.zip` de 3 CDNs → **404 ×3 en cada arranque** (driver del browser) |
| `www.googleapis.com` | `GET /oauth2/v2/userinfo` ×2 |
| `lh3.googleusercontent.com` | foto de perfil (!) |
| **`daily-cloudcode-pa.googleapis.com`** | **todo el API de Code Assist** (ver abajo) |
| `play.googleapis.com` | `POST /log` ×2 (telemetría Clearcut) |

Secuencia en `daily-cloudcode-pa`: `loadCodeAssist` ×3 → `fetchAdminControls` → `fetchUserInfo` ×2 → `retrieveUserQuotaSummary` ×3 → `fetchAvailableModels` (25KB) → `listExperiments` ×2 → `writeTrajectoryAcls` → **`streamGenerateContent?alt=sse`** ×2 (título + respuesta) → `recordTrajectoryAnalytics`.

## 2. Headers (idénticos en todas las llamadas a daily-cloudcode-pa)

```
Host: daily-cloudcode-pa.googleapis.com
User-Agent: antigravity/cli/1.1.28 (aidev_client; os_type=linux; arch=amd64; cl=978129418; auth_method=consumer)
Authorization: Bearer ya29....            (access token OAuth, ~1h)
Content-Type: application/json
Accept-Encoding: gzip
```

**No manda `X-Goog-Api-Client`** (el IDE 2.0.x sí lo mandaba: `google-cloud-sdk vscode_cloudshelleditor/0.1`).

Respuesta trae `x-cloudaicompanion-trace-id`, `Server: ESF`, `Server-Timing: gfet4t7; dur=NNN`.

## 3. OAuth — ⚠️ scope nuevo `aicode`

- client_id: el de Antigravity (`1071006060591-...apps.googleusercontent.com`, ver .env)
- redirect `http://localhost:51121/oauth-callback`, PKCE S256
- scopes reales del token de agy 1.1.28 (según `oauth2.googleapis.com/tokeninfo`):
  `openid email profile https://www.googleapis.com/auth/aicode cloud-platform cclog experimentsandconfigs userinfo.email userinfo.profile`
- **`https://www.googleapis.com/auth/aicode` es nuevo** — el bridge pedía solo 5 scopes (sin aicode). Un refresh_token conserva los scopes del consentimiento original, así que **después de actualizar SCOPES hay que volver a hacer login** (`python3 auth-login.py`); el refresh_token viejo seguirá dando 401 en daily-cloudcode-pa aunque el código esté bien.

Verificación del token del bridge: `curl -s "https://oauth2.googleapis.com/tokeninfo?access_token=$TOKEN" | jq .scope` debe incluir `auth/aicode`.

## 3b. Verificado en vivo (2026-09-09)

Con un access token del CLI y **el body mínimo del patch** (sin tools, sin `labels.model_enum`):
- `retrieveUserQuotaSummary` → 200, los 4 buckets
- `fetchAvailableModels` → 200
- `streamGenerateContent?alt=sse` con `gemini-3.8-flash-low` → `"text": "OK"`, `promptTokenCount: 10` (vs 13,558 vía agy: el bridge no arrastra el system prompt del CLI)
→ `model_enum` y los params `toolAction/toolSummary` son opcionales.

## 4. `retrieveUserQuotaSummary` (sin agy, directo)

```
POST /v1internal:retrieveUserQuotaSummary
{"project": "aicode-consumers"}
```
→ `{"groups":[{displayName, description, buckets:[{bucketId: gemini-weekly|gemini-5h|3p-weekly|3p-5h, window, remainingFraction, resetTime, description}]}], "description"}` (sin wrapper `response` — el RPC local sí lo envuelve).

## 5. `streamGenerateContent?alt=sse` — request "agent" (la llamada real)

```json
{
  "project": "aicode-consumers",
  "requestId": "agent/<conversation_id>/<epoch_ms>/<trajectory_id>/<step>",
  "model": "gemini-3.8-flash-low",
  "userAgent": "antigravity",
  "requestType": "agent",
  "request": {
    "contents": [ {"role":"user","parts":[{"text":"..."}]} ],
    "systemInstruction": {"role":"user","parts":[{"text":"<system prompt ~13k tokens>"}]},
    "tools": [ {"functionDeclarations":[ ... 50+ tools; cada una con params extra requeridos "toolAction" y "toolSummary" (STRING) ... ]} ],
    "labels": {
      "last_step_index": "0",
      "model_enum": "MODEL_PLACEHOLDER_M320",
      "request_id": "<trajectory_id>-0",
      "trajectory_id": "<uuid>",
      "used_claude": "false",
      "used_claude_conservative": "false",
      "used_non_gemini_model": "false"
    },
    "generationConfig": {
      "maxOutputTokens": 65536,
      "thinkingConfig": {"includeThoughts": true, "thinkingBudget": 1000}
    },
    "sessionId": "-3750763034362895579"
  }
}
```

Notas:
- **`model`** va con el alias de agy tal cual (`gemini-3.8-flash-low`); el backend responde `modelVersion: "gemini-3.8-flash"`. El effort se traduce a `thinkingBudget` (low = **1000**; medium/high pendientes de capturar).
- **`labels.model_enum`** es el enum interno (`MODEL_PLACEHOLDER_M320` = 3.8-flash-low). El mapa alias→enum está en `GetUserStatus.cascadeModelConfigData.clientModelConfigs[].modelOrAlias.model` (RPC local) y probablemente en `fetchAvailableModels`. Es una label de analytics; probablemente opcional.
- `sessionId` es un int64 aleatorio como string; se reutiliza entre llamadas de la misma sesión.
- `thoughtSignature` aparece en los parts de respuesta — para multi-turno hay que devolverlo (el bridge ya lo hace desde el commit 5c8d68e).

### Request "checkpoint" (título de conversación)

Misma forma, pero `requestType: "checkpoint"`, `requestId: "checkpoint/<uuid>"`, `model: "gemini-3.1-flash-lite"`, `thinkingBudget: 0`, `maxOutputTokens: 1024`, sin tools ni labels. Es una segunda llamada por turno — el bridge NO la necesita.

## 6. Respuesta SSE

```
data: {"response":{"candidates":[{"content":{"role":"model","parts":[{"text":"OK"}]}}],"usageMetadata":{"promptTokenCount":13558,"candidatesTokenCount":1,"totalTokenCount":13559,"cachedContentTokenCount":8129},"modelVersion":"gemini-3.8-flash","responseId":"..."},"traceId":"...","metadata":{}}
data: {"response":{"candidates":[{"content":{"role":"model","parts":[{"thoughtSignature":"...","text":""}]},"finishReason":"STOP"}],"usageMetadata":{...}}, ...}
```

Formato Gemini estándar envuelto en `response`. `cachedContentTokenCount` explica los 5k vs 13k tokens entre runs.

## 7. Diff contra el bridge (commit 7-jul)

| | agy 1.1.28 | bridge viejo | patch |
|---|---|---|---|
| Host | daily-cloudcode-pa | cloudcode-pa | `ASSIST_URL` → daily (env `ANTIGRAVITY_ASSIST_URL`) |
| User-Agent | antigravity/cli/1.1.28 (…) | antigravity/2.0.6 darwin/arm64 | `AGY_USER_AGENT` (env `AGY_CLI_VERSION`, `AGY_CLI_CL`) |
| X-Goog-Api-Client | no | sí | quitado |
| project | aicode-consumers | loadCodeAssist | loadCodeAssist con fallback `aicode-consumers` |
| requestId / userAgent / requestType | sí | no | agregados (`agent/...`) |
| request.sessionId / labels | sí | no | agregados |
| thinkingConfig | sí (por effort) | no | agregado (`_effort_from_model`, tabla `AGY_THINKING_BUDGET`) |
| systemInstruction.role | "user" | (sin role) | agregado |
| gemini-3.1-pro-high | funciona | marcado broken | re-habilitado |

## 8. Cómo capturar más (medium/high budgets, Claude, tools)

```bash
mitmdump -p 8080 -w /tmp/agy.flows          # ventana 1
# ventana 2, un run por modelo:
for m in gemini-3.8-flash-medium gemini-3.8-flash-high claude-sonnet-4-6; do
  echo '{"event":"user","message":{"content":"responde unicamente con la palabra: OK"}}' \
   | HTTPS_PROXY=http://127.0.0.1:8080 SSL_CERT_FILE=/root/.mitmproxy/mitmproxy-ca-cert.pem \
     HOME=~/.agy-test agy --model $m --input-format stream-json --output-format stream-json --disable-slash-commands >/dev/null
done
mitmdump -nr /tmp/agy.flows --flow-detail 4 '~u streamGenerateContent' | grep -nE '"model"|thinkingBudget|model_enum|used_claude'
```
