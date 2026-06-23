# Handoff — Antigravity → OpenAI Bridge

> Documento de traspaso. Léelo completo antes de tocar nada.
> Última actualización: 2026-06-23

---

## 1. TL;DR (qué estamos construyendo)

Un **mini-server HTTP OpenAI-compatible** que envuelve una cuenta de
**Antigravity / Gemini Code Assist** (OAuth Google) para que clientes
tipo **Hermes**, Open WebUI, Boba, BetterGPT, etc. puedan usarla
poniendo `Base URL = http://HOST:8080/v1`.

**Por qué:** la cuenta de Antigravity ya estaba autorizada y con tokens
válidos en `~/.local/share/opencode/auth.json`, pero no había forma de
consumirla desde un cliente OpenAI estándar. Este bridge cierra ese
hueco.

```
┌──────────┐    OpenAI API    ┌────────────────────┐   HTTPS   ┌──────────────────────┐
│  Hermes  │ ───────────────► │ antigravity-bridge │ ────────► │ cloudcode-pa.google   │
│  WebUI   │   /v1/chat/...   │  Flask :8080       │  Bearer   │ :loadCodeAssist      │
│  Boba    │                  │                    │  +project │ :generateContent     │
└──────────┘                  └────────────────────┘           │ :streamGenerateContent│
                                                                └──────────────────────┘
```

---

## 2. Stack

| Pieza              | Detalle                                                  |
|--------------------|----------------------------------------------------------|
| Lenguaje           | Python 3 (probado en Debian 12)                          |
| HTTP               | Flask 3.x                                                |
| Upstream HTTP      | requests 2.31+                                           |
| Auth source        | `~/.cache/opencode/packages/opencode-antigravity-auth/`  |
|                    | `dist/src/constants.js` (CLIENT_ID + CLIENT_SECRET)      |
| Cuenta source      | `~/.config/opencode/antigravity-accounts.json`           |
| Token cache        | `~/.local/share/opencode/auth.json`                      |

**Sin base de datos.** Todo se rehidrata leyendo los 3 archivos de arriba
al arrancar. El bridge reescribe `auth.json` solo cuando refresca el
access_token (cada ~1h).

---

## 3. Hallazgos clave (los gotchas que descubrimos)

Estos 4 puntos son los que nos hicieron perder tiempo. Documentados
para no repetirlos:

1. **`fingerprint.platform = "MACOS"` no es enum válido** para el
   endpoint `:loadCodeAssist`. Los enums aceptados son
   `PLATFORM_UNSPECIFIED | ANDROID | IOS | WEB | LINUX`.
   El bridge **fuerza `PLATFORM_UNSPECIFIED`** si la plataforma
   guardada no está en la whitelist.

2. **`refresh_token` en el JSON a veces trae un `|` al final**
   (`"...5Durnk|"`). Hay que hacer `.rstrip("|")` antes de mandar a
   Google o el refresh rebota con `invalid_grant`.

3. **`auth.json.google.projectId = ""`** por defecto. Hay que llamar a
   `:loadCodeAssist` una vez para obtenerlo (`zealous-audio-jb2z8`
   en esta cuenta). El bridge lo hace al arrancar y lo cachea en
   memoria.

4. **Credenciales OAuth NO están en el JSON de la cuenta.** Vienen
   embebidas en el paquete npm `opencode-antigravity-auth` (constantes
   `ANTIGRAVITY_CLIENT_ID` / `ANTIGRAVITY_CLIENT_SECRET`). Por eso
   sacamos todo de `constants.js` con regex, no las hardcodeamos.

---

## 4. Credenciales — dónde vive cada cosa

| Llave                   | Ubicación                                                                          |
|-------------------------|------------------------------------------------------------------------------------|
| `CLIENT_ID`             | `constants.js` → `ANTIGRAVITY_CLIENT_ID`                                           |
| `CLIENT_SECRET`         | `constants.js` → `ANTIGRAVITY_CLIENT_SECRET`                                       |
| `refresh_token`         | `antigravity-accounts.json` → `accounts[0].refreshToken`                           |
| `access_token`          | `auth.json` → `google.access` (cache, se refresca solo)                            |
| `projectId`             | `auth.json` → `google.projectId` (cache; auto-fetch si falta)                      |
| `userAgent` / `apiClient` | `antigravity-accounts.json` → `accounts[0].fingerprint.*`                        |

**Importante:** los paths son configurables vía env vars:
`ANTIGRAVITY_CONST`, `ANTIGRAVITY_ACCOUNTS`, `ANTIGRAVITY_AUTH`.

---

## 5. server.py

El archivo completo está en este mismo directorio (`server.py`).
Puntos de entrada:

- `class Auth` — carga credenciales estáticas, refresca token, persiste.
- `oai_to_gemini()` — convierte `messages` OpenAI → `contents` Gemini
  + separa `system` a `systemInstruction`.
- `build_req()` — arma el body para `:generateContent` /
  `:streamGenerateContent`. Inyecta `project` y `model`.
- `extract_text()` — saca el texto de la respuesta Gemini (con o sin
  wrapper `response`).
- `GET /health` — sanity check.
- `GET /v1/models` — lista modelos hardcodeada (ver TODO §9).
- `POST /v1/chat/completions` — soporta `stream: true` (SSE) y modo
  bloqueante.

**Headers que se mandan upstream** (críticos para no ser marcados como
bot):

```
Authorization:        Bearer <access_token>
Content-Type:         application/json
User-Agent:           antigravity/2.0.6 darwin/arm64
X-Goog-Api-Client:    google-cloud-sdk vscode_cloudshelleditor/0.1
```

---

## 6. Instalación (un solo bloque)

Pegar tal cual en la terminal del server (Debian):

```bash
mkdir -p ~/antigravity-bridge && cd ~/antigravity-bridge && \
pip install -q flask requests && \
cat > server.py <<'SERVER_EOF'
#!/usr/bin/env python3
"""Antigravity -> OpenAI compatible bridge. v0.1"""
from __future__ import annotations
import argparse, json, os, re, sys, threading, time, uuid
from pathlib import Path
import requests
from flask import Flask, Response, jsonify, request

CONST_PATH = Path(os.environ.get("ANTIGRAVITY_CONST",
    "/root/.cache/opencode/packages/opencode-antigravity-auth@latest/node_modules/opencode-antigravity-auth/dist/src/constants.js"))
ACCOUNTS_PATH = Path(os.environ.get("ANTIGRAVITY_ACCOUNTS",
    "/root/.config/opencode/antigravity-accounts.json"))
AUTH_PATH = Path(os.environ.get("ANTIGRAVITY_AUTH",
    "/root/.local/share/opencode/auth.json"))
ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal"
TOKEN_URL  = "https://oauth2.googleapis.com/token"

MODELS = [
    {"id":"gemini-2.5-pro","object":"model","owned_by":"google","created":1735689600},
    {"id":"gemini-2.5-flash","object":"model","owned_by":"google","created":1735776000},
    {"id":"gemini-2.0-flash","object":"model","owned_by":"google","created":1727654400},
    {"id":"gemini-2.0-flash-thinking","object":"model","owned_by":"google","created":1735776000},
]

class Auth:
    def __init__(self):
        self._lock=threading.Lock(); self._access=None; self._expires_at=0
        self._client_id=self._client_secret=self._refresh_token=self._project_id=self._email=None
        self._user_agent="antigravity/2.0.6 darwin/arm64"
        self._api_client="google-cloud-sdk vscode_cloudshelleditor/0.1"
        self._platform="PLATFORM_UNSPECIFIED"; self._ide_type="ANTIGRAVITY"
        self._load_static()
    def _load_static(self):
        if CONST_PATH.exists():
            src=CONST_PATH.read_text()
            if m:=re.search(r'ANTIGRAVITY_CLIENT_ID\s*=\s*"([^"]+)"',src): self._client_id=m.group(1)
            if m:=re.search(r'ANTIGRAVITY_CLIENT_SECRET\s*=\s*"([^"]+)"',src): self._client_secret=m.group(1)
        if ACCOUNTS_PATH.exists():
            try:
                d=json.loads(ACCOUNTS_PATH.read_text())
                a=(d.get("accounts") or [{}])[0]
                self._email=a.get("email")
                self._refresh_token=(a.get("refreshToken") or a.get("refresh_token") or "").rstrip("|")
                fp=a.get("fingerprint") or {}; cm=fp.get("clientMetadata") or {}
                self._user_agent=fp.get("userAgent",self._user_agent)
                self._api_client=fp.get("apiClient",self._api_client)
                p=cm.get("platform","") if isinstance(cm,dict) else ""
                if p not in {"PLATFORM_UNSPECIFIED","ANDROID","IOS","WEB","LINUX"}: p="PLATFORM_UNSPECIFIED"
                self._platform=p; self._ide_type=cm.get("ideType","ANTIGRAVITY") if isinstance(cm,dict) else "ANTIGRAVITY"
            except Exception as e: print(f"[auth] warn: {e}",file=sys.stderr)
        if AUTH_PATH.exists():
            try:
                g=(json.loads(AUTH_PATH.read_text()) or {}).get("google") or {}
                if g.get("projectId"): self._project_id=g["projectId"]
                if g.get("access"): self._access=g["access"]
                if g.get("expires"): self._expires_at=int(g["expires"])
            except Exception: pass
    def get_token(self):
        with self._lock:
            now=int(time.time()*1000)
            if self._access and self._expires_at>now+30000: return self._access
            if not(self._client_id and self._client_secret and self._refresh_token):
                raise RuntimeError("faltan credenciales OAuth")
            r=requests.post(TOKEN_URL,data={"client_id":self._client_id,"client_secret":self._client_secret,
                "refresh_token":self._refresh_token,"grant_type":"refresh_token"},timeout=20)
            r.raise_for_status()
            t=r.json()
            if "access_token" not in t: raise RuntimeError(f"refresh sin access_token: {t}")
            self._access=t["access_token"]; self._expires_at=now+int(t.get("expires_in",3600))*1000
            self._persist(); return self._access
    def _persist(self):
        if not AUTH_PATH.exists(): return
        try:
            a=json.loads(AUTH_PATH.read_text()); a.setdefault("google",{})
            a["google"]["access"]=self._access; a["google"]["expires"]=self._expires_at
            AUTH_PATH.write_text(json.dumps(a,indent=2)); AUTH_PATH.chmod(0o600)
        except Exception as e: print(f"[auth] persist warn: {e}",file=sys.stderr)
    def get_project_id(self):
        if self._project_id: return self._project_id
        at=self.get_token()
        body={"metadata":{"ideType":self._ide_type,"platform":self._platform,"pluginVersion":"2.0.6"}}
        r=requests.post(f"{ASSIST_URL}:loadCodeAssist",json=body,
            headers={"Authorization":f"Bearer {at}","Content-Type":"application/json",
                     "User-Agent":self._user_agent,"X-Goog-Api-Client":self._api_client},timeout=30)
        r.raise_for_status()
        p=r.json().get("cloudaicompanionProject")
        self._project_id = p.get("id") if isinstance(p,dict) else (p if isinstance(p,str) else None)
        if not self._project_id: raise RuntimeError("loadCodeAssist no devolvio project")
        return self._project_id
    @property
    def user_agent(self): return self._user_agent
    @property
    def api_client(self): return self._api_client
    @property
    def email(self): return self._email

auth=Auth(); app=Flask(__name__)

def oai_to_gemini(msgs):
    sp=[]; contents=[]
    for m in msgs:
        role=m.get("role"); c=m.get("content","")
        if isinstance(c,list): c="".join(p.get("text","") for p in c if isinstance(p,dict) and p.get("type")=="text")
        if role=="system":
            if c: sp.append(c)
        elif role=="user": contents.append({"role":"user","parts":[{"text":c or " "}]})
        elif role=="assistant": contents.append({"role":"model","parts":[{"text":c or " "}]})
    return contents, "\n\n".join(sp)

def build_req(model, body, contents, sys_instr):
    req={"model":model if model.startswith("models/") else f"models/{model}",
         "project":auth.get_project_id(),
         "request":{"contents":contents,"generationConfig":{
             "temperature":body.get("temperature",1.0),
             "maxOutputTokens":body.get("max_tokens",8192),
             "topP":body.get("top_p",0.95)}}}
    if sys_instr: req["request"]["systemInstruction"]={"parts":[{"text":sys_instr}]}
    s=body.get("stop")
    if s: req["request"]["generationConfig"]["stopSequences"]=s if isinstance(s,list) else [s]
    return req

def hdrs():
    return {"Authorization":f"Bearer {auth.get_token()}","Content-Type":"application/json",
            "User-Agent":auth.user_agent,"X-Goog-Api-Client":auth.api_client}

def extract_text(payload):
    obj=payload.get("response",payload)
    try:
        cands=obj.get("candidates") or []
        if cands: return "".join(p.get("text","") for p in cands[0].get("content",{}).get("parts",[]) if isinstance(p,dict))
    except Exception: pass
    return ""

@app.route("/")
def index():
    return jsonify({"name":"antigravity-bridge","version":"0.1.0","openai_compatible":True,
                    "email":auth.email,"project_id":auth.get_project_id(),
                    "endpoints":["/health","/v1/models","/v1/chat/completions"]})

@app.route("/health")
def health():
    return jsonify({"status":"ok","email":auth.email,"project_id":auth.get_project_id(),
                    "token_expires_at":auth._expires_at,"now_ms":int(time.time()*1000)})

@app.route("/v1/models")
def list_models(): return jsonify({"object":"list","data":MODELS})

@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    body=request.get_json(force=True,silent=True) or {}
    model=body.get("model","gemini-2.5-flash")
    messages=body.get("messages",[])
    stream=bool(body.get("stream",False))
    if not messages: return jsonify({"error":{"message":"messages requerido","type":"invalid_request"}}),400
    contents,sys_instr=oai_to_gemini(messages)
    gr=build_req(model,body,contents,sys_instr)
    cid=f"chatcmpl-{uuid.uuid4().hex[:24]}"; cr=int(time.time())
    if stream:
        def gen():
            try:
                with requests.post(f"{ASSIST_URL}:streamGenerateContent?alt=sse",
                    json=gr,headers=hdrs(),stream=True,timeout=60) as resp:
                    if resp.status_code!=200:
                        yield f"data: {json.dumps({'error':{'message':resp.text,'code':resp.status_code}})}\n\n"
                        yield "data: [DONE]\n\n"; return
                    for line in resp.iter_lines():
                        if not line: continue
                        if line.startswith(b"data: "): line=line[6:]
                        try: ev=json.loads(line)
                        except: continue
                        t=extract_text(ev)
                        if t:
                            yield f"data: {json.dumps({'id':cid,'object':'chat.completion.chunk','created':cr,'model':model,'choices':[{'index':0,'delta':{'content':t},'finish_reason':None}]})}\n\n"
                    yield f"data: {json.dumps({'id':cid,'object':'chat.completion.chunk','created':cr,'model':model,'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error':{'message':str(e),'type':'server_error'}})}\n\n"
                yield "data: [DONE]\n\n"
        return Response(gen(),mimetype="text/event-stream",
                        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    try:
        resp=requests.post(f"{ASSIST_URL}:generateContent",json=gr,headers=hdrs(),timeout=60)
    except Exception as e:
        return jsonify({"error":{"message":str(e),"type":"upstream_error"}}),502
    if resp.status_code!=200:
        return jsonify({"error":{"message":resp.text,"code":resp.status_code}}),resp.status_code
    data=resp.json(); text=extract_text(data)
    u=data.get("usageMetadata",{}) or {}
    return jsonify({"id":cid,"object":"chat.completion","created":cr,"model":model,
        "choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}],
        "usage":{"prompt_tokens":u.get("promptTokenCount",0),
                 "completion_tokens":u.get("candidatesTokenCount",0),
                 "total_tokens":u.get("totalTokenCount",0)}})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--host",default=os.environ.get("HOST","127.0.0.1"))
    p.add_argument("--port",type=int,default=int(os.environ.get("PORT","8080")))
    a=p.parse_args()
    try:
        auth.get_token(); pid=auth.get_project_id()
        print(f"[bridge] email={auth.email}  project_id={pid}  token_exp={auth._expires_at}",flush=True)
    except Exception as e: print(f"[bridge] WARN init: {e}",flush=True)
    print(f"[bridge] http://{a.host}:{a.port}  models={[m['id'] for m in MODELS]}",flush=True)
    app.run(host=a.host,port=a.port,threaded=True,debug=False)

if __name__=="__main__": main()
SERVER_EOF
nohup python3 server.py --host 0.0.0.0 --port 8080 > ~/antigravity-bridge.log 2>&1 &
sleep 2
echo "=== Health ==="; curl -s http://127.0.0.1:8080/health
echo; echo "=== Models ==="; curl -s http://127.0.0.1:8080/v1/models
echo; echo "=== Chat ==="; curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"di hola en 5 palabras"}]}'
```

---

## 7. Tests rápidos

```bash
# Health
curl -s http://127.0.0.1:8080/health | jq

# Modelos
curl -s http://127.0.0.1:8080/v1/models | jq '.data[].id'

# Chat bloqueante
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"hola"}]}' | jq

# Chat streaming (verás chunks SSE)
curl -N http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","stream":true,"messages":[{"role":"user","content":"cuentame un chiste"}]}'
```

Log del server:

```bash
tail -f ~/antigravity-bridge.log
```

---

## 8. Conectar a Hermes (u otro cliente OpenAI-compatible)

| Campo          | Valor                          |
|----------------|--------------------------------|
| Base URL       | `http://<IP_DEL_SERVER>:8080/v1` |
| API key        | `sk-local` (no valida nada)    |
| Modelos        | los de `GET /v1/models`        |

Si Hermes está en otra máquina y el server solo escucha `127.0.0.1`,
arranca con `--host 0.0.0.0` y abre el puerto:

```bash
# arrancar público
nohup python3 server.py --host 0.0.0.0 --port 8080 > ~/antigravity-bridge.log 2>&1 &
# firewall
sudo ufw allow 8080/tcp   # o tu firewall preferido
```

---

## 9. TODO / siguientes pasos

1. **Claude vía Antigravity.** La cuenta tiene `claude` en
   `cachedQuota` pero el endpoint upstream es distinto
   (formato Anthropic-style). Hay que detectar el modelo y rutear.
2. **Lista de modelos dinámica.** Hoy `MODELS` está hardcodeada.
   Mejor: filtrar `cachedQuota` del `accounts.json` y mapear a IDs
   reales de Antigravity.
3. **Multimodal.** Aceptar `content: [{type:"image_url",...}]` y
   convertir a `parts: [{inlineData:...}]` de Gemini.
4. **Auth en el bridge.** Hoy no valida API key del cliente. Agregar
   `Authorization: Bearer <X-Bridge-Key>` opcional.
5. **systemd unit** para que arranque al boot.
6. **Términos / uso.** El tier actual es `free-tier`; respeta los
   rate limits de Gemini Code Assist.

---

## 10. Prompt de arranque para Kimi Code

Pégale esto a Kimi Code como **primer mensaje** después de cargar
este repo:

```
Eres el continuador de este proyecto. Léete handoff.md COMPLETO
(包括 los gotchas de la sección 3 y el TODO de la sección 9) antes
de tocar nada.

Tu trabajo:
1. Confirmar que entendiste la arquitectura (Antigravity → bridge →
   OpenAI-compatible → Hermes).
2. Correr la instalación de la sección 6 y validar que los 3 tests
   de la sección 7 pasan.
3. Si algo falla, NO inventes — diagnostica con `tail
   ~/antigravity-bridge.log` y los gotchas de la sección 3.
4. Próxima tarea sugerida: implementar el TODO #1 (Claude vía
   Antigravity) usando el patrón de detección por prefijo de modelo.

No rompas nada que ya funciona. No hardcodees credenciales. No
cambies la interfaz OpenAI-compatible — clientes como Hermes ya
están integrados contra esa forma.
```

---

## 11. Changelog

| Fecha       | Cambio                                                       |
|-------------|--------------------------------------------------------------|
| 2026-06-23  | v0.1.0 — primer bridge funcional. Refresh token, `:loadCodeAssist`, `:generateContent`, `:streamGenerateContent` |
