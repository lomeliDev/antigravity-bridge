#!/usr/bin/env python3
"""
Antigravity -> OpenAI compatible bridge.

Run:
  pip install -r requirements.txt
  python3 server.py [--host 127.0.0.1] [--port 52847]

Environment variables:
  HOST / PORT               - listen address/port
  BRIDGE_API_KEY            - optional API key for client authentication
  ANTIGRAVITY_CONST         - path to constants.js
  ANTIGRAVITY_ACCOUNTS      - path to antigravity-accounts.json
  ANTIGRAVITY_AUTH          - path to auth.json

Endpoints:
  GET  /health
  GET  /v1/models
  GET  /v1/models/<model_id>
  POST /v1/chat/completions      (stream + non-stream)

Compatible with OpenAI clients such as: Hermes, Open WebUI, Boba, BetterGPT, etc.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, request

# ============================================================
# Config
# ============================================================
CONST_PATH = Path(os.environ.get(
    "ANTIGRAVITY_CONST",
    "/root/.cache/opencode/packages/opencode-antigravity-auth@latest/"
    "node_modules/opencode-antigravity-auth/dist/src/constants.js",
))
ACCOUNTS_PATH = Path(os.environ.get(
    "ANTIGRAVITY_ACCOUNTS",
    "/root/.config/opencode/antigravity-accounts.json",
))
AUTH_PATH = Path(os.environ.get(
    "ANTIGRAVITY_AUTH",
    "/root/.local/share/opencode/auth.json",
))

BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY")

ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Models that are known to be broken through the Antigravity API.
# These are filtered from the /v1/models listing to avoid confusing users.
_BROKEN_MODELS: frozenset[str] = frozenset({
    "gemini-2.5-pro",       # 503 "No capacity" — consistently unavailable
    "gemini-3.1-pro-high",  # 400 INVALID_ARGUMENT — unsupported by API
})
MODELS: list[dict[str, Any]] = [
    {"id": "gemini-2.5-pro",             "object": "model", "owned_by": "google", "created": 1735689600},
    {"id": "gemini-2.5-flash",           "object": "model", "owned_by": "google", "created": 1735776000},
    {"id": "gemini-2.0-flash",           "object": "model", "owned_by": "google", "created": 1727654400},
    {"id": "gemini-2.0-flash-thinking",  "object": "model", "owned_by": "google", "created": 1735776000},
]

# ============================================================
# Auth — loads credentials from constants.js / accounts.json / auth.json
# ============================================================
class Auth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._access: str | None = None
        self._expires_at: int = 0
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._refresh_token: str | None = None
        self._project_id: str | None = None
        self._user_agent = "antigravity/2.0.6 darwin/arm64"
        self._api_client = "google-cloud-sdk vscode_cloudshelleditor/0.1"
        self._email: str | None = None
        self._load_static()

    def _load_static(self) -> None:
        # 1) OAuth client from the npm package
        if CONST_PATH.exists():
            src = CONST_PATH.read_text()
            if m := re.search(r'ANTIGRAVITY_CLIENT_ID\s*=\s*"([^"]+)"', src):
                self._client_id = m.group(1)
            if m := re.search(r'ANTIGRAVITY_CLIENT_SECRET\s*=\s*"([^"]+)"', src):
                self._client_secret = m.group(1)
        # 2) Refresh token + fingerprint from the account
        if ACCOUNTS_PATH.exists():
            try:
                data = json.loads(ACCOUNTS_PATH.read_text())
                accts = data.get("accounts") or []
                if accts:
                    acct = accts[0]
                    self._email = acct.get("email")
                    rt = acct.get("refreshToken") or acct.get("refresh_token") or ""
                    self._refresh_token = rt.strip("|")
                    fp = acct.get("fingerprint") or {}
                    cm = fp.get("clientMetadata") or {}
                    self._user_agent = fp.get("userAgent", self._user_agent)
                    self._api_client = fp.get("apiClient", self._api_client)
                    # MACOS is not a valid platform enum for loadCodeAssist
                    plat = cm.get("platform", "") if isinstance(cm, dict) else ""
                    if plat not in {"PLATFORM_UNSPECIFIED", "ANDROID", "IOS", "WEB", "LINUX"}:
                        plat = "PLATFORM_UNSPECIFIED"
                    self._platform = plat
                    self._ide_type = cm.get("ideType", "ANTIGRAVITY") if isinstance(cm, dict) else "ANTIGRAVITY"
            except Exception as e:
                print(f"[auth] warn reading accounts: {e}", file=sys.stderr)
        # 3) Cached token + projectId from auth.json
        if AUTH_PATH.exists():
            try:
                auth = json.loads(AUTH_PATH.read_text())
                g = auth.get("google") or {}
                if g.get("projectId"):
                    self._project_id = g["projectId"]
                if g.get("access"):
                    self._access = g["access"]
                if g.get("expires"):
                    self._expires_at = int(g["expires"])
            except Exception:
                pass

    def _platform_safe(self) -> str:
        return getattr(self, "_platform", "PLATFORM_UNSPECIFIED")

    def _ide_safe(self) -> str:
        return getattr(self, "_ide_type", "ANTIGRAVITY")

    def get_token(self) -> str:
        with self._lock:
            now_ms = int(time.time() * 1000)
            if self._access and self._expires_at > now_ms + 30_000:
                return self._access
            if not (self._client_id and self._client_secret and self._refresh_token):
                raise RuntimeError("Missing OAuth credentials (constants.js / accounts.json)")
            r = requests.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=20,
            )
            r.raise_for_status()
            tok = r.json()
            if "access_token" not in tok:
                raise RuntimeError(f"Refresh response missing access_token: {tok}")
            self._access = tok["access_token"]
            self._expires_at = now_ms + int(tok.get("expires_in", 3600)) * 1000
            self._persist()
            return self._access

    def _persist(self) -> None:
        if not AUTH_PATH.exists():
            return
        try:
            auth = json.loads(AUTH_PATH.read_text())
            auth.setdefault("google", {})
            auth["google"]["access"] = self._access
            auth["google"]["expires"] = self._expires_at
            AUTH_PATH.write_text(json.dumps(auth, indent=2))
            AUTH_PATH.chmod(0o600)
        except Exception as e:
            print(f"[auth] warn persisting token: {e}", file=sys.stderr)

    def get_project_id(self) -> str:
        if self._project_id:
            return self._project_id
        at = self.get_token()
        body = {"metadata": {
            "ideType": self._ide_safe(),
            "platform": self._platform_safe(),
            "pluginVersion": "2.0.6",
        }}
        r = requests.post(
            f"{ASSIST_URL}:loadCodeAssist",
            json=body,
            headers={
                "Authorization": f"Bearer {at}",
                "Content-Type": "application/json",
                "User-Agent": self._user_agent,
                "X-Goog-Api-Client": self._api_client,
            },
            timeout=30,
        )
        r.raise_for_status()
        proj = r.json().get("cloudaicompanionProject")
        if isinstance(proj, dict):
            self._project_id = proj.get("id")
        elif isinstance(proj, str):
            self._project_id = proj
        if not self._project_id:
            raise RuntimeError("loadCodeAssist did not return cloudaicompanionProject")
        return self._project_id

    @property
    def user_agent(self) -> str: return self._user_agent
    @property
    def api_client(self) -> str: return self._api_client
    @property
    def email(self) -> str | None: return self._email


auth = Auth()
app = Flask(__name__)

# ============================================================
# Dynamic model list cache
# ============================================================
_MODEL_CACHE: list[dict[str, Any]] | None = None
_MODEL_CACHE_TS: float = 0.0
_MODEL_CACHE_TTL: float = 300.0  # 5 minutes


def _provider_to_owned_by(provider: str) -> str:
    p = (provider or "").lower()
    if "anthropic" in p:
        return "anthropic"
    if "openai" in p:
        return "openai"
    return "google"


def fetch_available_models() -> list[dict[str, Any]]:
    """Fetch models from :fetchAvailableModels and return an OpenAI-compatible list."""
    global _MODEL_CACHE, _MODEL_CACHE_TS
    now = time.time()
    if _MODEL_CACHE is not None and (now - _MODEL_CACHE_TS) < _MODEL_CACHE_TTL:
        return _MODEL_CACHE
    try:
        r = requests.post(
            f"{ASSIST_URL}:fetchAvailableModels",
            headers=headers(),
            json={"project": auth.get_project_id()},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        models: list[dict[str, Any]] = []
        for model_id, info in (data.get("models") or {}).items():
            if not info.get("displayName"):
                continue
            # Skip internal experiment IDs that are not public chat models.
            if model_id.startswith(("chat_", "tab_")):
                continue
            # Filter models that are known to be broken via this API.
            if model_id in _BROKEN_MODELS:
                continue
            models.append({
                "id": model_id,
                "object": "model",
                "owned_by": _provider_to_owned_by(info.get("modelProvider", "")),
                "created": int(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).timestamp()),
            })
        models.sort(key=lambda m: m["id"])
        _MODEL_CACHE = models
        _MODEL_CACHE_TS = now
        print(f"[models] fetched {len(models)} models", flush=True)
        return models
    except Exception as e:
        print(f"[models] fetch failed: {e}", file=sys.stderr, flush=True)
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE
        return MODELS


# ============================================================
# Helpers
# ============================================================
def _download_image(url: str, timeout: int = 20) -> tuple[str, str]:
    """Return (mime_type, base64_data) for an image given by URL or data URI."""
    if url.startswith("data:"):
        header, _, b64 = url.partition(",")
        mime = header.split(";")[0].replace("data:", "")
        return mime or "image/png", b64
    r = requests.get(url, headers={"User-Agent": "antigravity-bridge/0.1"}, timeout=timeout)
    r.raise_for_status()
    mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return mime, base64.b64encode(r.content).decode("ascii")


def oai_content_to_gemini_parts(content: str | list[Any]) -> list[dict[str, Any]]:
    """Convert OpenAI content (string or text/image_url list) to Gemini parts."""
    if isinstance(content, str):
        return [{"text": content or " "}]
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "text":
            parts.append({"text": item.get("text", " ")})
        elif itype == "image_url":
            image_url = item.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
            if url:
                try:
                    mime, b64 = _download_image(url)
                    parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                except Exception as e:
                    print(f"[vision] warn: {e}", file=sys.stderr, flush=True)
                    parts.append({"text": "[image unavailable]"})
    if not parts:
        parts = [{"text": " "}]
    return parts


def _tool_call_id_to_name(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Map tool_call_id -> function name from assistant messages."""
    mapping: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []) or []:
            if isinstance(tc, dict):
                name = tc.get("function", {}).get("name")
                tid = tc.get("id")
                if name and tid:
                    mapping[tid] = name
        fc = msg.get("function_call")
        if isinstance(fc, dict) and fc.get("name"):
            mapping["legacy_function_call"] = fc["name"]
    return mapping


def _tool_result_to_response(raw: Any) -> dict[str, Any]:
    """Convert a tool message content into a functionResponse object."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"result": raw}
    return {"result": raw}


def oai_messages_to_gemini(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """OpenAI chat -> Gemini (contents + system_instruction). Supports text, images and tools."""
    tool_names = _tool_call_id_to_name(messages)
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            if isinstance(content, str):
                if content:
                    system_parts.append(content)
            elif isinstance(content, list):
                system_parts.append("".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ))
        elif role == "user":
            contents.append({"role": "user", "parts": oai_content_to_gemini_parts(content)})
        elif role == "assistant":
            # Assistant messages should not carry images; coerce to text.
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            parts: list[dict[str, Any]] = []
            text = content or "(tool call)"
            parts.append({"text": text})
            # Convert OpenAI tool_calls to Gemini functionCall parts.
            # Generate synthetic IDs matching the tool_call_id format so
            # the Antigravity backend can match tool_use ↔ tool_result.
            for tc in msg.get("tool_calls", []) or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name", "")
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception:
                    args = args_str
                fc_id = tc.get("id") or f"call_{uuid.uuid4().hex[:24]}"
                parts.append({"functionCall": {"name": name, "args": args, "id": fc_id}})
                # Remember the id for matching tool responses
                tool_names[fc_id] = name
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            tid = msg.get("tool_call_id", "")
            name = msg.get("name") or tool_names.get(tid) or "unknown"
            response = _tool_result_to_response(content)
            fr: dict[str, Any] = {"name": name, "response": response}
            if tid:
                fr["id"] = tid
            contents.append({"role": "user", "parts": [{"functionResponse": fr}]})
        elif role == "function":
            # Legacy OpenAI function result format.
            name = msg.get("name") or "unknown"
            response = _tool_result_to_response(content)
            contents.append({"role": "user", "parts": [{"functionResponse": {"name": name, "response": response}}]})
    return contents, "\n\n".join(system_parts)


def _apply_response_format(body: dict[str, Any], generation_config: dict[str, Any]) -> None:
    """Map OpenAI response_format to Antigravity/Gemini generationConfig."""
    rf = body.get("response_format")
    if not isinstance(rf, dict):
        return
    fmt = rf.get("type")
    if fmt == "json_object":
        generation_config["responseMimeType"] = "application/json"
    elif fmt == "json_schema":
        schema = rf.get("json_schema", {}).get("schema")
        if schema:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = _clean_gemini_schema(schema)


def _model_max_output_tokens(model_id: str) -> int:
    """Return the max output tokens for known models.
    Flash/lite/low/agent: 8192. Pure Gemini pro/thinking: 65536. Claude/GPT: 8192."""
    mid = (model_id or "").lower()
    # Claude, GPT, and any "lite"/"low"/"agent" variant: 8192
    if any(kw in mid for kw in ("claude", "gpt", "lite", "low", "agent")):
        return 8192
    # Flash models: 8192
    if "flash" in mid:
        return 8192
    # Pure pro/thinking models (no flash, no lite, no low, no agent): 65536
    if "pro" in mid or "thinking" in mid:
        return 65536
    return 8192  # safe default


def build_gemini_request(model: str, body: dict[str, Any], contents: list, system_instr: str) -> dict[str, Any]:
    # Antigravity expects the model id without the "models/" prefix.
    model_id = model[7:] if model.startswith("models/") else model
    raw_max_tokens = body.get("max_completion_tokens") or body.get("max_tokens", 8192)
    max_output = min(int(raw_max_tokens), _model_max_output_tokens(model_id))
    generation_config: dict[str, Any] = {
        "temperature": body.get("temperature", 1.0),
        "maxOutputTokens": max_output,
        "topP": body.get("top_p", 0.95),
    }
    if "seed" in body and isinstance(body["seed"], int):
        generation_config["seed"] = body["seed"]
    n = body.get("n", 1)
    if isinstance(n, int) and n > 1:
        generation_config["candidateCount"] = min(n, 8)
    _apply_response_format(body, generation_config)
    req: dict[str, Any] = {
        "project": auth.get_project_id(),
        "model": model_id,
        "request": {
            "contents": contents,
            "generationConfig": generation_config,
        },
    }
    if system_instr:
        req["request"]["systemInstruction"] = {"parts": [{"text": system_instr}]}
    stop = body.get("stop")
    if stop:
        req["request"]["generationConfig"]["stopSequences"] = (
            stop if isinstance(stop, list) else [stop]
        )
    tools = body.get("tools")
    if tools:
        gemini_tools = oai_tools_to_antigravity(tools)
        if gemini_tools:
            req["request"]["tools"] = gemini_tools
            mode = oai_tool_choice_to_mode(body.get("tool_choice"), _is_claude_model(model_id))
            if mode:
                req["request"]["toolConfig"] = {"functionCallingConfig": {"mode": mode}}
    return req


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {auth.get_token()}",
        "Content-Type": "application/json",
        "User-Agent": auth.user_agent,
        "X-Goog-Api-Client": auth.api_client,
    }


def _extract_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    obj = payload.get("response", payload)
    try:
        return obj.get("candidates") or []
    except Exception:
        return []


def _candidate_text(candidate: dict[str, Any]) -> str:
    try:
        parts = candidate.get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except Exception:
        return ""


def _candidate_tool_calls(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    try:
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            if not isinstance(part, dict) or "functionCall" not in part:
                continue
            fc = part["functionCall"]
            args = fc.get("args", {})
            calls.append({
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": fc.get("name", ""),
                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                },
            })
    except Exception:
        pass
    return calls


def extract_text(payload: dict[str, Any]) -> str:
    """Extract text from the first candidate (simple compatibility)."""
    cands = _extract_candidates(payload)
    return _candidate_text(cands[0]) if cands else ""


def _is_claude_model(model_id: str) -> bool:
    return model_id.lower().startswith("claude-")


# JSON Schema fields that Gemini Function Calling rejects outright.
# Ported from opencode-antigravity-auth's toGeminiSchema() unsupported list.
_UNSUPPORTED_SCHEMA_FIELDS = frozenset({
    "additionalProperties",
    "$schema",
    "$id",
    "$comment",
    "$ref",
    "$defs",
    "definitions",
    "contentMediaType",
    "contentEncoding",
    "if",
    "then",
    "else",
    "not",
    "patternProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "dependentRequired",
    "dependentSchemas",
    "propertyNames",
    "minContains",
    "maxContains",
    # OpenAI-specific extras not present in the Gemini/API subset
    "strict",
    "title",
    "schema",
})

# Constraint fields that Gemini rejects but whose meaning we preserve as a
# description hint (matches the original plugin's moveConstraintsToDescription).
_CONSTRAINT_FIELDS = frozenset({
    "minLength",
    "maxLength",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "minItems",
    "maxItems",
    "format",
    "multipleOf",
})

# Composite keywords whose sub-schemas also need cleaning.
_COMPOSITE_KEYS = ("anyOf", "allOf", "oneOf", "any_of", "all_of", "one_of")

_EMPTY_SCHEMA_PLACEHOLDER = "_placeholder"
_EMPTY_SCHEMA_DESCRIPTION = "Placeholder. Always pass true."


def _log_failed_request(gemini_req: dict[str, Any], status_code: int, response_text: str) -> None:
    """Log a failing upstream request to disk for post-mortem debugging."""
    try:
        sanitized = json.loads(json.dumps(gemini_req))
        # Truncate huge content blobs
        if "request" in sanitized:
            req = sanitized["request"]
            if isinstance(req.get("contents"), list):
                req["contents"] = f"<{len(req['contents'])} contents>"
            if isinstance(req.get("systemInstruction"), dict):
                si_text = json.dumps(req["systemInstruction"])
                req["systemInstruction"] = f"<systemInstruction: {len(si_text)} chars>"
        dump = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status_code": status_code,
            "response": response_text[:5000],
            "request": sanitized,
            "tools_summary": [],
        }
        tools = sanitized.get("request", {}).get("tools", [])
        for tg in (tools if isinstance(tools, list) else []):
            for fd in (tg.get("functionDeclarations", []) if isinstance(tg, dict) else []):
                params = fd.get("parameters", {})
                props = params.get("properties", {}) if isinstance(params, dict) else {}
                dump["tools_summary"].append({
                    "name": fd.get("name"),
                    "props_count": len(props),
                    "required_count": len(params.get("required", []) if isinstance(params, dict) else []),
                })
        dump_path = Path(f"/tmp/bridge_error_{int(time.time())}.json")
        dump_path.write_text(json.dumps(dump, indent=2, default=str))
        print(f"[upstream] full request dump → {dump_path}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _add_description_hint(schema: dict[str, Any], hint: str) -> dict[str, Any]:
    """Append an informational hint to a schema's description field."""
    existing = schema.get("description", "")
    if existing:
        schema["description"] = f"{existing} ({hint})"
    else:
        schema["description"] = hint
    return schema


def _move_constraint_to_description(
    schema: dict[str, Any], key: str, value: Any
) -> dict[str, Any]:
    """Turn a rejected constraint keyword into a description hint."""
    if key in ("minLength", "maxLength", "minItems", "maxItems", "multipleOf"):
        hint = f"{key}: {value}"
    elif key in ("minimum", "maximum"):
        hint = f"{key}: {value}"
    elif key in ("exclusiveMinimum", "exclusiveMaximum"):
        hint = f"{key}: {value}"
    elif key == "pattern":
        hint = f"pattern: {value}"
    elif key == "format":
        hint = f"format: {value}"
    else:
        hint = f"{key}: {value}"
    return _add_description_hint(schema, hint)


def _convert_const_to_enum(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert { const: x } -> { enum: [x] } so the value is not lost."""
    if "const" in schema and "enum" not in schema:
        schema = dict(schema)
        schema["enum"] = [schema.pop("const")]
    return schema


def _flatten_type_array(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten type arrays like ['string', 'null'] to a single type + hint."""
    t = schema.get("type")
    if not isinstance(t, list):
        return schema
    if not t:
        schema = dict(schema)
        schema["type"] = "STRING"
        return schema
    non_null = [x for x in t if x != "null"]
    if len(non_null) >= 1:
        schema = dict(schema)
        schema["type"] = non_null[0]
        if "null" in t:
            schema = _add_description_hint(schema, "nullable")
    else:
        # All types are "null" — fallback to string
        schema = dict(schema)
        schema["type"] = "STRING"
        schema = _add_description_hint(schema, "nullable (was: type null)")
    return schema


def _merge_allof(schema: dict[str, Any]) -> dict[str, Any]:
    """Merge allOf branches into a single object schema."""
    allof = schema.get("allOf")
    if not isinstance(allof, list) or not allof:
        return schema
    merged: dict[str, Any] = {}
    required: list[str] = []
    for sub in allof:
        if not isinstance(sub, dict):
            continue
        for k, v in sub.items():
            if k == "properties" and isinstance(v, dict):
                merged.setdefault("properties", {})
                merged["properties"].update(v)
            elif k == "required" and isinstance(v, list):
                required.extend(v)
            elif k not in merged:
                merged[k] = v
    # Top-level schema wins over allOf branches.
    for k, v in schema.items():
        if k == "allOf":
            continue
        if k == "properties" and isinstance(v, dict):
            merged.setdefault("properties", {})
            merged["properties"].update(v)
        elif k == "required" and isinstance(v, list):
            required.extend(v)
        else:
            merged[k] = v
    if required:
        merged["required"] = list(dict.fromkeys(required))
    return merged


def _flatten_anyof_oneof(schema: dict[str, Any]) -> dict[str, Any]:
    """Detect const/enum-of-consts or nullable type unions in anyOf/oneOf.
    Complex unions that can't be flattened are stripped and replaced with a
    looser STRING type + hint to avoid Gemini rejecting anyOf/oneOf outright."""
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if not isinstance(branches, list) or not branches:
            continue

        # Pattern: [{const: a}, {const: b}, ...] -> enum: [a, b]
        consts: list[Any] = []
        for b in branches:
            if isinstance(b, dict) and "const" in b:
                consts.append(b["const"])
            elif (
                isinstance(b, dict)
                and isinstance(b.get("enum"), list)
                and len(b["enum"]) == 1
            ):
                consts.append(b["enum"][0])
        if consts and len(consts) == len(branches):
            schema = dict(schema)
            schema.pop(key)
            schema["enum"] = consts
            return schema

        # Pattern: [{type: "string"}, {type: "null"}] -> type: "string" + nullable hint
        types = [
            b["type"]
            for b in branches
            if isinstance(b, dict) and isinstance(b.get("type"), str)
        ]
        if types and len(types) == len(branches) and "null" in types:
            schema = dict(schema)
            schema.pop(key)
            non_null = [t for t in types if t != "null"]
            if len(non_null) == 1:
                schema["type"] = non_null[0]
                schema = _add_description_hint(schema, "nullable")
            elif len(non_null) > 1:
                schema["type"] = non_null[0]
                schema = _add_description_hint(schema, f"types: {', '.join(non_null)}")
            return schema

        # Fallback: unflattenable union — strip it to avoid Gemini 400 error.
        schema = dict(schema)
        schema.pop(key)
        schema["type"] = "STRING"
        schema = _add_description_hint(schema, f"union of {len(branches)} schemas (simplified from {key})")

    return schema


def _clean_gemini_schema(obj: Any) -> Any:
    """Recursively transform a JSON Schema into a Gemini-compatible schema.

    Mirrors the original opencode-antigravity-auth pipeline:
    - Strips fields Gemini rejects (see _UNSUPPORTED_SCHEMA_FIELDS).
    - Preserves constraint semantics as description hints.
    - Converts const -> enum, merges allOf, flattens anyOf/oneOf unions.
    - Flattens type arrays and upper-cases type names.
    - Filters 'required' to only include keys that exist in 'properties'.
    - Ensures array schemas have an 'items' field.
    - Injects a placeholder for empty object schemas.
    """
    if isinstance(obj, dict):
        # Unwrap a nested 'schema' key ONLY when it is a JSON-Schema wrapper:
        #  - obj has no 'type' (so it's not itself a schema)
        #  - obj['schema'] is a dict that DOES have 'type' or 'properties' (it's a real schema)
        # This prevents corrupting schemas that legitimately have a property named 'schema'.
        if (
            "schema" in obj
            and isinstance(obj["schema"], dict)
            and "type" not in obj
            and "properties" not in obj
            and ("type" in obj["schema"] or "properties" in obj["schema"])
        ):
            obj = obj["schema"]

        # Structural normalizations (do these before recursive cleaning so the
        # resulting shape is simpler).
        obj = _convert_const_to_enum(obj)
        obj = _merge_allof(obj)
        obj = _flatten_anyof_oneof(obj)
        obj = _flatten_type_array(obj)

        # Collect declared property names so we can validate required entries.
        property_names: set[str] = set()
        if isinstance(obj.get("properties"), dict):
            property_names = {
                k for k in obj["properties"].keys() if isinstance(k, str)
            }

        cleaned: dict[str, Any] = {}
        # Seed description first so constraint hints append to it rather than
        # being overwritten when the original description is processed later.
        if isinstance(obj.get("description"), str):
            cleaned["description"] = obj["description"]

        for key, value in obj.items():
            if key in _UNSUPPORTED_SCHEMA_FIELDS:
                continue

            if key in _CONSTRAINT_FIELDS or key in ("minimum", "maximum"):
                # Preserve the constraint meaning as a description hint.
                cleaned = _move_constraint_to_description(cleaned, key, value)
                continue

            if key == "type" and isinstance(value, str):
                # Gemini API expects uppercase type names.
                cleaned[key] = value.upper()
            elif key == "description":
                # Already seeded above; don't overwrite it with hints appended.
                if "description" not in cleaned:
                    cleaned[key] = value
            elif key == "properties" and isinstance(value, dict):
                cleaned[key] = {
                    prop: _clean_gemini_schema(sub)
                    for prop, sub in value.items()
                }
            elif key == "items":
                cleaned[key] = _clean_gemini_schema(value)
            elif key in _COMPOSITE_KEYS and isinstance(value, list):
                cleaned[key] = [_clean_gemini_schema(item) for item in value]
            elif key == "required" and isinstance(value, list):
                valid = [
                    r for r in value
                    if isinstance(r, str) and (not property_names or r in property_names)
                ]
                if valid:
                    cleaned[key] = valid
            else:
                cleaned[key] = value

        # Ensure object schemas have a properties map.
        if cleaned.get("type") in ("object", "OBJECT") and "properties" not in cleaned:
            cleaned["properties"] = {}
        if "type" not in cleaned and "properties" in cleaned:
            cleaned["type"] = "OBJECT"

        # Empty object schemas need a placeholder property.
        if (
            cleaned.get("type") == "OBJECT"
            and isinstance(cleaned.get("properties"), dict)
            and not cleaned["properties"]
        ):
            cleaned["properties"] = {
                _EMPTY_SCHEMA_PLACEHOLDER: {
                    "type": "BOOLEAN",
                    "description": _EMPTY_SCHEMA_DESCRIPTION,
                }
            }
            cleaned.setdefault("required", [])
            if _EMPTY_SCHEMA_PLACEHOLDER not in cleaned["required"]:
                cleaned["required"].append(_EMPTY_SCHEMA_PLACEHOLDER)

        # Gemini API requires array schemas to declare items.
        if cleaned.get("type") == "ARRAY" and "items" not in cleaned:
            cleaned["items"] = {"type": "STRING"}

        return cleaned

    if isinstance(obj, list):
        return [_clean_gemini_schema(item) for item in obj]

    return obj


def _normalize_tool_parameters(parameters: Any) -> dict[str, Any]:
    """Return a Gemini-compatible JSON schema for function parameters."""
    if not isinstance(parameters, dict):
        return {"type": "OBJECT", "properties": {}}

    parameters = _clean_gemini_schema(parameters)
    if not isinstance(parameters, dict):
        return {"type": "OBJECT", "properties": {}}

    if parameters.get("type") in ("object", "OBJECT") and "properties" not in parameters:
        parameters["properties"] = {}
    if "type" not in parameters:
        parameters["type"] = "OBJECT"

    return parameters


def oai_tools_to_antigravity(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI tools [{type:function, function:{...}}] to Gemini format."""
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if tool.get("type") == "function" else tool
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        parameters = _normalize_tool_parameters(fn.get("parameters"))
        declarations.append({
            "name": name,
            "description": fn.get("description", ""),
            "parameters": parameters,
        })
    if not declarations:
        return []
    return [{"functionDeclarations": declarations}]


def oai_tool_choice_to_mode(tool_choice: Any, is_claude: bool) -> str | None:
    """Map OpenAI tool_choice to Antigravity functionCallingConfig.mode."""
    if is_claude and tool_choice != "none":
        # Antigravity plugin forces VALIDATED for Claude when tools are present.
        return "VALIDATED"
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return "NONE"
        if tool_choice == "required":
            return "ANY"
        return "AUTO"
    if isinstance(tool_choice, dict):
        return "ANY"
    return "AUTO"


def extract_tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract functionCalls from the first candidate as OpenAI tool_calls."""
    cands = _extract_candidates(payload)
    return _candidate_tool_calls(cands[0]) if cands else []


# ============================================================
# API key authentication
# ============================================================
def _check_api_key() -> tuple[dict[str, Any], int] | None:
    """Validate the optional BRIDGE_API_KEY. Returns (error, status) if rejected."""
    if not BRIDGE_API_KEY:
        return None
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"error": {"message": "Missing Authorization header", "type": "authentication_error"}}, 401
    provided = auth_header[7:]
    if provided != BRIDGE_API_KEY:
        return {"error": {"message": "Invalid API key", "type": "authentication_error"}}, 401
    return None


# ============================================================
# Routes
# ============================================================
@app.route("/")
def index():
    return jsonify({
        "name": "antigravity-bridge",
        "version": "0.1.0",
        "openai_compatible": True,
        "email": auth.email,
        "project_id": auth.get_project_id(),
        "endpoints": ["/health", "/v1/models", "/v1/chat/completions"],
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "email": auth.email,
        "project_id": auth.get_project_id(),
        "token_expires_at": auth._expires_at,
        "now_ms": int(time.time() * 1000),
    })


@app.route("/v1/models")
def list_models():
    if err := _check_api_key():
        return jsonify(err[0]), err[1]
    return jsonify({"object": "list", "data": fetch_available_models()})


@app.route("/v1/models/<path:model_id>")
def get_model(model_id: str):
    if err := _check_api_key():
        return jsonify(err[0]), err[1]
    models = fetch_available_models()
    for m in models:
        if m["id"] == model_id:
            return jsonify(m)
    return jsonify({"error": {"message": "model not found", "type": "invalid_request_error"}}), 404


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    if err := _check_api_key():
        return jsonify(err[0]), err[1]

    body = request.get_json(force=True, silent=True) or {}
    model = body.get("model", "gemini-2.5-flash")
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))

    if not messages:
        return jsonify({"error": {"message": "messages is required", "type": "invalid_request_error"}}), 400

    contents, system_instr = oai_messages_to_gemini(messages)
    gemini_req = build_gemini_request(model, body, contents, system_instr)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    stream_options = body.get("stream_options") or {}
    include_usage = bool(stream_options.get("include_usage"))

    if stream:
        def gen():
            try:
                url = f"{ASSIST_URL}:streamGenerateContent?alt=sse"
                with requests.post(url, json=gemini_req, headers=headers(),
                                   stream=True, timeout=60) as resp:
                    if resp.status_code != 200:
                        print(f"[upstream] STREAM ERROR {resp.status_code}: {resp.text[:2000]}", file=sys.stderr, flush=True)
                        _log_failed_request(gemini_req, resp.status_code, resp.text)
                        err = {"error": {"message": resp.text, "type": "upstream_error",
                                         "code": resp.status_code}}
                        yield f"data: {json.dumps(err)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    emitted_tool_calls = False
                    stream_usage: dict[str, Any] = {}
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        if line.startswith(b"data: "):
                            line = line[6:]
                        try:
                            ev = json.loads(line)
                        except Exception:
                            continue
                        um = (ev.get("response") or ev).get("usageMetadata")
                        if isinstance(um, dict):
                            stream_usage = um
                        text = extract_text(ev)
                        if text:
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": text},
                                    "finish_reason": None,
                                }],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                        tool_calls = extract_tool_calls(ev)
                        if tool_calls:
                            emitted_tool_calls = True
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [
                                            {"index": i, **tc}
                                            for i, tc in enumerate(tool_calls)
                                        ],
                                    },
                                    "finish_reason": None,
                                }],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                    final: dict[str, Any] = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if emitted_tool_calls else "stop"}],
                    }
                    if include_usage:
                        final["usage"] = {
                            "prompt_tokens": stream_usage.get("promptTokenCount", 0),
                            "completion_tokens": stream_usage.get("candidatesTokenCount", 0),
                            "total_tokens": stream_usage.get("totalTokenCount", 0),
                        }
                    yield f"data: {json.dumps(final)}\n\n"
                    yield "data: [DONE]\n\n"
            except Exception as e:
                err = {"error": {"message": str(e), "type": "server_error"}}
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"

        return Response(
            gen(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-stream
    try:
        resp = requests.post(f"{ASSIST_URL}:generateContent",
                             json=gemini_req, headers=headers(), timeout=60)
    except Exception as e:
        return jsonify({"error": {"message": str(e), "type": "upstream_error"}}), 502
    if resp.status_code != 200:
        print(f"[upstream] ERROR {resp.status_code}: {resp.text[:2000]}", file=sys.stderr, flush=True)
        # Log the failing request (without full message content) for debugging
        _log_failed_request(gemini_req, resp.status_code, resp.text)
        return jsonify({"error": {"message": resp.text, "type": "upstream_error",
                                  "code": resp.status_code}}), resp.status_code

    data = resp.json()
    candidates = _extract_candidates(data)
    usage = (data.get("response") or data).get("usageMetadata", {}) or {}
    choices: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        text = _candidate_text(candidate)
        tool_calls = _candidate_tool_calls(candidate)
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        choices.append({
            "index": idx,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        })
    return jsonify({
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": choices,
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    })


# ============================================================
# Main
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "52847")))
    args = parser.parse_args()

    # Eager-init: refresh token and load projectId at startup.
    try:
        auth.get_token()
        pid = auth.get_project_id()
        print(f"[bridge] email      : {auth.email}", flush=True)
        print(f"[bridge] project_id : {pid}", flush=True)
        print(f"[bridge] token exp  : {auth._expires_at}", flush=True)
    except Exception as e:
        print(f"[bridge] WARN init: {e}", flush=True)

    print(f"[bridge] listening  : http://{args.host}:{args.port}", flush=True)
    try:
        models = fetch_available_models()
        print(f"[bridge] models     : {len(models)} available", flush=True)
    except Exception as e:
        print(f"[bridge] models     : static fallback ({e})", flush=True)
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
