# Reverse-engineering playbook — how the Antigravity protocol was captured

Purpose: when the bridge breaks (401/400/404 from Google, new agy release, new scope), this is the procedure to
re-capture what the real client sends and diff it against what the bridge sends. Everything below was done
in Sep 2026 against agy 1.1.28; it took ~1 hour and every step is reproducible.

Golden rule: **never guess a field name. Capture it.** The bridge broke in July 2026 because it imitated the
Antigravity IDE 2.0.x; the CLI moved to a different host, User-Agent, body shape and an extra OAuth scope.

---

## 0. Tools you need

```bash
pip install mitmproxy --break-system-packages   # HTTPS MITM proxy (agy does NOT pin certs)
apt install jq                                   # JSON on the shell
# ss / curl / tcpdump come with the OS
```

Also handy: an **isolated agy home** so captures don't include your MCPs/skills/hooks and don't pollute your real
conversations (see the agy-kit: `HOME=~/.agy-test agy ...`).

---

## 1. Layer 1 — who does the client talk to (no MITM, 30 s)

Run agy with its stdin held open so it starts its servers without sending a prompt, then look at sockets:

```bash
mkfifo /tmp/agy-fifo
HOME=~/.agy-test agy --input-format stream-json --output-format stream-json < /tmp/agy-fifo > /tmp/agy-out.txt 2>&1 &
AGYPID=$!; exec 9>/tmp/agy-fifo; sleep 3

ss -tlnp | grep "pid=$AGYPID,"                                 # local listeners (its JSON-RPC server)
echo '{"event":"user","message":{"content":"responde unicamente con la palabra: OK"}}' >&9
for i in 1 2 3 4 5 6; do ss -tnp | grep "pid=$AGYPID," | grep -v 127.0.0.1; sleep 0.5; done | sort -u   # outbound
exec 9>&-; rm -f /tmp/agy-fifo; kill $AGYPID
```

Resolve the remote IPs (`dig -x <ip> +short`). This tells you the hosts before decrypting anything.

The local listener (two ports: one TLS, one plain HTTP) answers JSON-RPC without auth:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:<port>/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary
curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:<port>/exa.language_server_pb.LanguageServerService/GetUserStatus
```

`GetUserStatus.cascadeModelConfigData.clientModelConfigs[]` maps model ids to internal enums
(`MODEL_PLACEHOLDER_Mxx`) — the same values as `labels.model_enum`.

---

## 2. Layer 2 — decrypt HTTPS with mitmproxy

agy is a Go binary: it honors `HTTPS_PROXY` and `SSL_CERT_FILE`, and does not pin certificates.

```bash
# terminal 1: capture to a file
mitmdump -p 8080 -w /tmp/agy.flows

# terminal 2: one run through the proxy (isolated home)
echo '{"event":"user","message":{"content":"responde unicamente con la palabra: OK"}}' \
  | HTTPS_PROXY=http://127.0.0.1:8080 HTTP_PROXY=http://127.0.0.1:8080 \
    SSL_CERT_FILE=/root/.mitmproxy/mitmproxy-ca-cert.pem \
    HOME=~/.agy-test agy --model gemini-3.8-flash-low --input-format stream-json --output-format stream-json --disable-slash-commands
```

Notes:
- `SSL_CERT_FILE` must be an **absolute** path (`~` points to the fake HOME).
- The first `mitmdump` run generates the CA in `~/.mitmproxy/`.
- If a Go client ever pins certs you'd see a TLS error instead of flows — then the fallback is `--log-file` /
  debug logs of the client, or patching, not covered here.

### Reading the capture

```bash
mitmdump -nr /tmp/agy.flows --flow-detail 1                              # list of requests
mitmdump -nr /tmp/agy.flows --flow-detail 4 '~u retrieveUserQuotaSummary' # headers + body of one endpoint
mitmdump -nr /tmp/agy.flows --flow-detail 4 '~u streamGenerateContent' > /tmp/model-call.txt
grep -nE '"(model|requestType|requestId|userAgent|sessionId)"|thinkingBudget|model_enum' /tmp/model-call.txt
```

The model call is big (agy's system prompt is ~13k tokens + 50 tools): grep it, don't read it.

To capture one request per model (e.g. to read `thinkingConfig` per tier):

```bash
for m in $(HOME=~/.agy-test agy models 2>/dev/null | grep -vi fetching | awk '{print $1}'); do
  echo '{"event":"user","message":{"content":"responde unicamente con la palabra: OK"}}' \
   | HTTPS_PROXY=http://127.0.0.1:8080 SSL_CERT_FILE=/root/.mitmproxy/mitmproxy-ca-cert.pem HOME=~/.agy-test \
     agy --model $m --input-format stream-json --output-format stream-json --disable-slash-commands >/dev/null 2>&1
done
```

---

## 3. What to compare (the fingerprint checklist)

Diff **each** of these between the capture and what the bridge sends (`BRIDGE_DEBUG=1` logs the bridge body):

| Item | Where in the capture | Where in the bridge |
|---|---|---|
| Host | request line | `ASSIST_URL` / `ANTIGRAVITY_ASSIST_URL` |
| `User-Agent` | request headers | `AGY_USER_AGENT` (`AGY_CLI_VERSION`, `AGY_CLI_CL`, `AGY_AUTH_METHOD`) |
| Other headers (`X-Goog-Api-Client`, `Accept-Encoding`…) | request headers | `headers()` |
| OAuth **scopes** | `curl "https://oauth2.googleapis.com/tokeninfo?access_token=$TOKEN" \| jq .scope` | `Auth.SCOPES` + `auth-login.py` |
| OAuth client_id / redirect | the `accounts.google.com/o/oauth2/v2/auth?...` URL agy opens on login | `.env` / `REDIRECT_URI` |
| Body top-level: `project`, `requestId` format, `model`, `userAgent`, `requestType` | model call | `build_gemini_request()` |
| `request.sessionId`, `request.labels.*` | model call | idem |
| `generationConfig` (`thinkingConfig`, `maxOutputTokens`, temperature…) | model call, per model | catalog (`fetchAvailableModels`) + `AGY_THINKING_BUDGET` |
| `systemInstruction.role` | model call | idem |
| Tools shape (`functionDeclarations`, extra required params) | model call with a tool run (`--dangerously-skip-permissions`) | `oai_tools_to_antigravity()` |
| Boot endpoints & order (`loadCodeAssist`, `fetchAvailableModels`, `retrieveUserQuotaSummary`…) | flow list | `fetch_quota()`, `fetch_available_models()` |
| Response shape (`response.candidates`, `usageMetadata`, `thoughtSignature`, `groundingMetadata`) | model call response | `_candidate_text()` / `_candidate_extras()` |

### What changed in Sep 2026 (IDE 2.0.6 → CLI 1.1.28)

| | before (bridge, July) | after (capture) |
|---|---|---|
| Host | `cloudcode-pa.googleapis.com` | `daily-cloudcode-pa.googleapis.com` |
| User-Agent | `antigravity/2.0.6 darwin/arm64` | `antigravity/cli/1.1.28 (aidev_client; os_type=linux; arch=amd64; cl=978129418; auth_method=consumer)` |
| `X-Goog-Api-Client` | sent | **not sent** |
| `project` | from `loadCodeAssist` | `"aicode-consumers"` (consumer auth) |
| body | `project, model, request` | `+ requestId ("agent/<conv>/<ms>/<traj>/<step>"), userAgent:"antigravity", requestType:"agent"` |
| `request` | `contents, generationConfig, systemInstruction` | `+ sessionId, labels{model_enum,…}, thinkingConfig, systemInstruction.role:"user"` |
| Scopes | 5 | **+ `openid`, `https://www.googleapis.com/auth/aicode`** (missing scope = 401) |

---

## 4. Probing the backend directly (no agy)

With a fresh access token you can hit the API yourself. Get one from the isolated home after any agy run
(the real home's file may be stale — always verify with tokeninfo):

```bash
TOKEN=$(jq -r '.token.access_token' ~/.agy-test/.gemini/antigravity-cli/antigravity-oauth-token)
curl -s "https://oauth2.googleapis.com/tokeninfo?access_token=$TOKEN" | jq '{email, expires_in, scope}'   # must be valid
UA='antigravity/cli/1.1.28 (aidev_client; os_type=linux; arch=amd64; cl=978129418; auth_method=consumer)'
H=https://daily-cloudcode-pa.googleapis.com/v1internal        # NOTE: use ${H}:… in zsh ($H:x is a modifier!)

curl -s -X POST "${H}:retrieveUserQuotaSummary" -H "Authorization: Bearer $TOKEN" -H "User-Agent: $UA" \
  -H 'Content-Type: application/json' -d '{"project":"aicode-consumers"}' | jq
curl -s -X POST "${H}:fetchAvailableModels" ... -d '{"project":"aicode-consumers"}' | jq '.models|keys'
```

Feature probes (this is how `web_search` / `url_context` / `code_execution` / image output were found):

```bash
probe() { jq -cn --argjson r "$2" '{project:"aicode-consumers",requestId:"agent/0/1/0/1",model:"gemini-3.8-flash-low",userAgent:"antigravity",requestType:"agent",request:($r+{sessionId:"1",labels:{last_step_index:"0",request_id:"x-0",trajectory_id:"x",used_claude:"false",used_claude_conservative:"false",used_non_gemini_model:"false"}})}' > /tmp/probe.json
  echo "=== $1 ==="; curl -s -X POST "${H}:generateContent" -H "Authorization: Bearer $TOKEN" -H "User-Agent: $UA" -H 'Content-Type: application/json' -d @/tmp/probe.json | head -c 900; echo; }
probe googleSearch  '{"contents":[{"role":"user","parts":[{"text":"que fecha es hoy?"}]}],"tools":[{"googleSearch":{}}]}'
probe urlContext    '{"contents":[{"role":"user","parts":[{"text":"resume https://opencode.ai/docs/"}]}],"tools":[{"urlContext":{}}]}'
probe codeExecution '{"contents":[{"role":"user","parts":[{"text":"suma de primos < 1000, ejecuta codigo"}]}],"tools":[{"codeExecution":{}}]}'
```

Reading the result: `candidates` with content → feature exists; `400 INVALID_ARGUMENT` with a field name → wrong
shape (the message tells you the field); `404` HTML → endpoint doesn't exist (e.g. `embedContent`).

---

## 5. Gotchas that cost time

- **Stale token in `~/.gemini/antigravity-cli/antigravity-oauth-token`**: agy refreshes in memory; the file of the
  home that ran is the fresh one. Always check `tokeninfo` before blaming the protocol.
- **zsh eats `$H:streamGenerateContent`** (`:s` is a history modifier) → 404 on `/v1internalent`. Use `${H}:...`.
- **zsh `echo "$json" | jq`** interprets `\n` inside the JSON → parse error. Use `jq ... <<< "$json"`.
- **mitmdump output has ANSI/`\r`** — don't copy tokens from it with `awk`; read them from the token file.
- **agy print mode (`-p`) is broken** (writes to the controlling tty, hangs without one): use
  `--input-format stream-json --output-format stream-json` with `{"event":"user","message":{"content":"..."}}` on stdin.
- **GitHub push-protection** blocks commits containing the OAuth client id/secret → keep them in `.env` only.
- agy tries to download `playwright-1.57.0-linux.zip` from 3 CDNs on every start (404 ×3) and calls
  `retrieveUserQuotaSummary` 3 times — noise, ignore it in the flow list.

---

## 6. Files in this repo produced by this process

| File | What |
|---|---|
| `docs/agy-cli-protocol.md` | The captured protocol (hosts, headers, OAuth, request/response bodies) |
| `docs/api-reference.md` | What the bridge accepts and how it maps to the above |
| `openapi.yaml` (`/docs`, `/api/spec.yml`) | Machine-readable spec |
| `docs/reverse-engineering.md` | This playbook |
