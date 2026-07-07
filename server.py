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
# Config — standalone (no longer dependent on OpenCode)
# ============================================================

# OAuth client credentials — Google's public gemini-cli desktop OAuth client.
# These are baked into every copy of the open-source gemini-cli npm package
# and are NOT confidential (desktop OAuth clients use PKCE for security).
# Values default to the npm package's public constants; override via env vars
# or .env file if Google ever rotates them.
ANTIGRAVITY_CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_CLIENT_ID",
    "",
)
ANTIGRAVITY_CLIENT_SECRET = os.environ.get(
    "ANTIGRAVITY_CLIENT_SECRET",
    "",
)

# Refresh token — set via BRIDGE_REFRESH_TOKEN env var or .env file.
# On first run, the bridge falls back to OpenCode's accounts.json for
# one-time migration. Set this to make the bridge fully standalone.
BRIDGE_REFRESH_TOKEN = os.environ.get("BRIDGE_REFRESH_TOKEN", "")

# Legacy paths (one-time migration fallback, optional)
ACCOUNTS_PATH = Path(os.environ.get(
    "ANTIGRAVITY_ACCOUNTS",
    "/root/.config/opencode/antigravity-accounts.json",
))

# Own auth file — no longer shares with OpenCode
AUTH_PATH = Path(os.environ.get(
    "ANTIGRAVITY_AUTH_PATH",
    str(Path(__file__).resolve().parent / "antigravity-auth.json"),
))

BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY")


# ============================================================
# Usage tracker (in-memory, reset on restart)
# ============================================================
class UsageTracker:
    """Thread-safe per-model usage tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._by_model: dict[str, dict[str, int]] = {}  # model -> {requests, errors, prompt, completion}
        self._started_at: float = time.time()

    def record(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error: bool = False,
    ) -> None:
        with self._lock:
            self._total_requests += 1
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens
            if error:
                self._total_errors += 1

            if model not in self._by_model:
                self._by_model[model] = {
                    "requests": 0, "errors": 0,
                    "prompt_tokens": 0, "completion_tokens": 0,
                }
            m = self._by_model[model]
            m["requests"] += 1
            m["prompt_tokens"] += prompt_tokens
            m["completion_tokens"] += completion_tokens
            if error:
                m["errors"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            models_sorted = sorted(
                self._by_model.items(),
                key=lambda kv: kv[1]["requests"],
                reverse=True,
            )
            return {
                "uptime_seconds": int(time.time() - self._started_at),
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "total_prompt_tokens": self._prompt_tokens,
                "total_completion_tokens": self._completion_tokens,
                "total_tokens": self._prompt_tokens + self._completion_tokens,
                "by_model": {
                    model: dict(stats) for model, stats in models_sorted
                },
            }


_usage = UsageTracker()

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
        # 1) OAuth client — hardcoded (public values, no longer reads from npm)
        self._client_id = ANTIGRAVITY_CLIENT_ID
        self._client_secret = ANTIGRAVITY_CLIENT_SECRET

        # 2) Refresh token — from env var first, fallback to OpenCode accounts.json
        used_env_token = False
        if BRIDGE_REFRESH_TOKEN:
            self._refresh_token = BRIDGE_REFRESH_TOKEN.strip("|")
            used_env_token = True

        # Still try to load email + fingerprint from accounts.json if available
        if ACCOUNTS_PATH.exists():
            try:
                data = json.loads(ACCOUNTS_PATH.read_text())
                accts = data.get("accounts") or []
                if accts:
                    acct = accts[0]
                    self._email = acct.get("email")
                    if not used_env_token:
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

        # 3) Cached token + projectId from own auth file
        if AUTH_PATH.exists():
            try:
                auth_data = json.loads(AUTH_PATH.read_text())
                if auth_data.get("access"):
                    self._access = auth_data["access"]
                if auth_data.get("expires"):
                    self._expires_at = int(auth_data["expires"])
                if auth_data.get("projectId"):
                    self._project_id = auth_data["projectId"]
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
                raise RuntimeError("Missing OAuth credentials. Set BRIDGE_REFRESH_TOKEN in .env or export the env var.")
            try:
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
            except requests.RequestException as e:
                raise RuntimeError(f"Token refresh network error: {e}")

            if not r.ok:
                err = _parse_google_oauth_error(r)
                # Auto-clear credentials on invalid_grant (token revoked / expired)
                if err.get("code") == "invalid_grant":
                    print(f"[auth] invalid_grant — clearing revoked credentials", file=sys.stderr)
                    self._clear_credentials()
                raise RuntimeError(
                    f"Token refresh failed ({r.status_code}): {err.get('message', r.text[:200])}"
                )

            tok = r.json()
            if "access_token" not in tok:
                raise RuntimeError(f"Refresh response missing access_token: {list(tok.keys())}")
            self._access = tok["access_token"]
            self._expires_at = now_ms + int(tok.get("expires_in", 3600)) * 1000
            # Google may rotate the refresh_token — save the new one if returned
            if "refresh_token" in tok and tok["refresh_token"] != self._refresh_token:
                self._refresh_token = tok["refresh_token"]
                _save_refresh_token_to_env()
                print(f"[auth] refresh_token rotated", file=sys.stderr)
            self._persist()
            return self._access

    def _clear_credentials(self) -> None:
        """Clear stored credentials after a fatal auth error (e.g., invalid_grant).
        Deletes the cached access token and comments out the refresh_token in .env."""
        self._access = None
        self._expires_at = 0
        self._refresh_token = None
        self._project_id = None
        # Delete cached auth file
        try:
            if AUTH_PATH.exists():
                AUTH_PATH.unlink()
        except Exception:
            pass
        # Comment out the token in .env so it doesn't retry on restart
        try:
            env_path = Path(__file__).resolve().parent / ".env"
            if env_path.exists():
                content = env_path.read_text()
                new_lines = []
                for line in content.splitlines():
                    if line.startswith("BRIDGE_REFRESH_TOKEN=") and not line.startswith("#"):
                        new_lines.append(f"# {line}  # revoked — run auth-login.py to re-authenticate")
                    else:
                        new_lines.append(line)
                env_path.write_text("\n".join(new_lines) + "\n")
        except Exception as e:
            print(f"[auth] warn clearing .env: {e}", file=sys.stderr)

    def _credential_health(self) -> dict:
        """Return credential health status (for /health endpoint)."""
        return {
            "has_refresh_token": bool(self._refresh_token),
            "has_access_token": bool(self._access),
            "access_expired": self._expires_at <= int(time.time() * 1000) if self._access else True,
            "email": self._email,
            "project_id": self._project_id,
        }

    def _persist(self) -> None:
        try:
            # Own simplified format — no longer nested under "google" key
            AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"access": self._access, "expires": self._expires_at}
            if self._project_id:
                data["projectId"] = self._project_id
            AUTH_PATH.write_text(json.dumps(data, indent=2))
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
        self._persist()  # save project_id to disk
        return self._project_id

    @property
    def user_agent(self) -> str: return self._user_agent
    @property
    def api_client(self) -> str: return self._api_client
    @property
    def email(self) -> str | None: return self._email


    # ── OAuth login flow (PKCE + local callback, same as opencode-antigravity-auth) ──
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    SCOPES = (
        "https://www.googleapis.com/auth/cloud-platform "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile "
        "https://www.googleapis.com/auth/cclog "
        "https://www.googleapis.com/auth/experimentsandconfigs"
    )
    REDIRECT_URI = "http://localhost:51121/oauth-callback"
    # Internal state for in-progress flow
    _auth_state: str | None = None
    _auth_code: str | None = None
    _auth_verifier: str | None = None
    _auth_code_event: Any = None  # threading.Event

    @staticmethod
    def _generate_pkce() -> tuple[str, str, str]:
        """Generate PKCE S256 verifier + challenge. Returns (verifier, challenge, state_payload)."""
        import hashlib
        verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        # Encode verifier into state like OpenCode: base64url(JSON)
        payload = json.dumps({"verifier": verifier, "projectId": ""})
        state = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
        return verifier, challenge, state

    def build_auth_url(self) -> str:
        """Build the Google OAuth authorization URL with PKCE."""
        from urllib.parse import urlencode
        verifier, challenge, state = self._generate_pkce()
        self._auth_verifier = verifier
        self._auth_state = state
        params = {
            "client_id": self._client_id,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, verifier: str = "") -> bool:
        """Exchange authorization code + PKCE verifier for tokens. Returns True on success."""
        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self.REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        if verifier:
            data["code_verifier"] = verifier
        r = requests.post(TOKEN_URL, data=data, timeout=20)
        r.raise_for_status()
        tok = r.json()
        if "refresh_token" not in tok:
            raise RuntimeError(f"No refresh_token in response: {list(tok.keys())}")

        self._refresh_token = tok["refresh_token"]
        self._access = tok.get("access_token")
        now_ms = int(time.time() * 1000)
        self._expires_at = now_ms + int(tok.get("expires_in", 3600)) * 1000

        # Extract email from id_token
        if "id_token" in tok:
            try:
                payload = data["id_token"].split(".")[1]
                payload += "=" * ((4 - len(payload) % 4) % 4)
                id_data = json.loads(base64.urlsafe_b64decode(payload))
                self._email = id_data.get("email", self._email)
            except Exception:
                pass

        self._persist()
        return True


auth = Auth()
app = Flask(__name__)


# ── Google OAuth error classification (matching opencode-antigravity-auth's parseOAuthErrorPayload) ──
def _parse_google_oauth_error(response: requests.Response) -> dict:
    """Parse Google OAuth error responses into a structured dict.
    Returns {'code': str|None, 'message': str, 'status': int}."""
    result: dict = {"code": None, "message": "", "status": response.status_code}
    try:
        text = response.text
    except Exception:
        text = ""
    if not text:
        result["message"] = f"HTTP {response.status_code}"
        return result
    try:
        payload = json.loads(text)
    except Exception:
        result["message"] = text[:200]
        return result
    if not isinstance(payload, dict):
        result["message"] = str(payload)[:200]
        return result
    # Google OAuth errors: {"error": "...", "error_description": "..."}
    code = payload.get("error")
    desc = payload.get("error_description", "")
    if isinstance(code, str):
        result["code"] = code
    elif isinstance(code, dict):
        result["code"] = code.get("status") or code.get("code")
        if not desc and code.get("message"):
            desc = code["message"]
    if desc:
        result["message"] = desc
    elif isinstance(code, str):
        result["message"] = code
    if not result["message"]:
        result["message"] = text[:200]
    return result


# Return JSON for 404s (Hermes and other clients expect JSON, not HTML).
@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": {"message": "Not found", "type": "invalid_request_error"}}), 404

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


def oai_messages_to_gemini(messages: list[dict[str, Any]], model_id: str = "") -> tuple[list[dict[str, Any]], str]:
    """OpenAI chat -> Gemini (contents + system_instruction). Supports text, images and tools."""
    tool_names = _tool_call_id_to_name(messages)
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    is_claude = _is_claude_model(model_id)
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
            tc_list = msg.get("tool_calls", []) or []
            has_tool_calls = bool(tc_list)

            # Gemini/Antigravity requires a signed thinking part before
            # functionCall parts in conversation history.  Claude rejects
            # the sentinel signature, so skip injection for Claude models.
            SENTINEL = "skip_thought_signature_validator"
            if has_tool_calls and not is_claude:
                parts.append({
                    "thought": True,
                    "text": text,
                    "thoughtSignature": SENTINEL,
                })
                text = None  # don't duplicate text
            if text:
                parts.append({"text": text})

            # Convert OpenAI tool_calls to Gemini functionCall parts.
            # The first functionCall part carries thought_signature at
            # the PART level (alongside functionCall, not inside it).
            # Parallel calls must NOT carry a signature (API requirement).
            first_fc = True
            for tc in tc_list:
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
                fc_part: dict[str, Any] = {"functionCall": {"name": name, "args": args, "id": fc_id}}
                if has_tool_calls and first_fc and not is_claude:
                    fc_part["thought_signature"] = SENTINEL
                    fc_part["thoughtSignature"] = SENTINEL
                    first_fc = False
                parts.append(fc_part)
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

    # Warn about OpenAI params that Antigravity does not support.
    _UNSUPPORTED_PARAMS = ("logprobs", "frequency_penalty", "presence_penalty", "logit_bias", "top_logprobs")
    for param in _UNSUPPORTED_PARAMS:
        if param in body and body[param] is not None and body[param] != 0:
            print(f"[bridge] WARN unsupported param '{param}' ignored", file=sys.stderr, flush=True)

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
    cred = auth._credential_health()
    return jsonify({
        "status": "ok",
        "email": auth.email,
        "project_id": auth.get_project_id(),
        "token_expires_at": auth._expires_at,
        "now_ms": int(time.time() * 1000),
        "credentials": cred,
    })


# ── Hermes-compatible optional endpoints ──────────────────────
# Hermes Dashboard calls these to show usage / billing / provider
# info.  The bridge does not track usage, so we return empty data
# that satisfies Hermes without errors in the UI.


@app.route("/v1/usage")
@app.route("/v1/dashboard/billing/usage")
@app.route("/dashboard/billing/usage")
def usage_stub():
    snap = _usage.snapshot()
    return jsonify(snap)


@app.route("/v1/billing/subscription")
@app.route("/dashboard/billing/subscription")
def subscription_stub():
    return jsonify({
        "has_payment_method": True,
        "soft_limit_usd": 999,
        "hard_limit_usd": 999,
        "system_hard_limit_usd": 999,
        "plan": {"id": "antigravity-bridge", "title": "Antigravity Bridge"},
    })


@app.route("/v1/models")
def list_models():
    return jsonify({"object": "list", "data": fetch_available_models()})


@app.route("/v1/models/<path:model_id>")
def get_model(model_id: str):
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

    contents, system_instr = oai_messages_to_gemini(messages, model)
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
                        _usage.record(model=model, error=True)
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
                    # Record usage from stream metadata
                    _usage.record(
                        model=model,
                        prompt_tokens=stream_usage.get("promptTokenCount", 0),
                        completion_tokens=stream_usage.get("candidatesTokenCount", 0),
                    )
                    yield f"data: {json.dumps(final)}\n\n"
                    yield "data: [DONE]\n\n"
            except Exception as e:
                _usage.record(model=model, error=True)
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
        _usage.record(model=model, error=True)
        # Log the failing request (without full message content) for debugging
        _log_failed_request(gemini_req, resp.status_code, resp.text)
        return jsonify({"error": {"message": resp.text, "type": "upstream_error",
                                  "code": resp.status_code}}), resp.status_code

    data = resp.json()
    candidates = _extract_candidates(data)
    usage = (data.get("response") or data).get("usageMetadata", {}) or {}
    _usage.record(
        model=model,
        prompt_tokens=usage.get("promptTokenCount", 0),
        completion_tokens=usage.get("candidatesTokenCount", 0),
    )
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
# OAuth login (local callback server, same approach as OpenCode)
# ============================================================
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Tiny HTTP server that captures the OAuth callback from Google."""

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)

        if parsed.path == "/oauth-callback":
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]
            error = qs.get("error", [None])[0]

            if error:
                msg = f"OAuth error: {error}"
                self._respond(400, msg, msg)
                auth._auth_code_event and auth._auth_code_event.set()
                return

            if state != auth._auth_state:
                msg = "OAuth state mismatch — possible CSRF attack"
                self._respond(400, msg, msg)
                return

            if code:
                auth._auth_code = code
                auth._auth_code_event and auth._auth_code_event.set()
                self._respond(200, "Authentication successful! You may close this window.",
                              "✅ Login successful! You can close this tab and return to the bridge.")
            else:
                msg = "No authorization code received"
                self._respond(400, msg, msg)
        else:
            self._respond(404, "Not found", "Not found")

    def _respond(self, status: int, title: str, body: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{title}</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;
align-items:center;min-height:100vh;margin:0;background:#0d1117;color:#e6edf3;}}
div{{text-align:center;padding:40px;}}</style></head>
<body><div><h2>{body}</h2></div></body></html>"""
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # suppress logs


def _start_callback_server(port: int, timeout: float = 120.0, event: threading.Event | None = None):
    """Run a temporary HTTP server to capture the OAuth callback.
    Blocks until the callback arrives or timeout expires."""
    server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    server.timeout = 1.0  # check event each second
    deadline = time.time() + timeout
    try:
        while time.time() < deadline and not (event and event.is_set()):
            server.handle_request()
    finally:
        server.server_close()


@app.route("/auth/login", methods=["POST"])
def auth_login_start():
    """Start OAuth login flow.
    Returns an auth_url to open in a browser. The bridge starts a background
    thread with a local callback server on port 51121 to capture the code."""
    try:
        auth._auth_code = None
        auth._auth_code_event = threading.Event()

        auth_url = auth.build_auth_url()  # PKCE — generates verifier + state internally

        # Start callback server in background thread
        def _bg():
            _start_callback_server(51121, timeout=120, event=auth._auth_code_event)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()

        return jsonify({
            "auth_url": auth_url,
            "message": f"Open this URL in your browser and authorize:\n{auth_url}",
            "state": auth._auth_state,
            "expires_in": 120,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/auth/login/manual", methods=["POST"])
def auth_login_manual():
    """Exchange a manually-pasted authorization code for tokens.
    Useful for remote servers where the local callback can't reach the bridge."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        code = body.get("code", "").strip()
        if not code:
            return jsonify({"error": "No authorization code provided.", "done": False}), 400

        auth.exchange_code(code, auth._auth_verifier or "")
        _save_refresh_token_to_env()

        return jsonify({
            "done": True,
            "email": auth.email,
            "message": "Authentication successful!",
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "done": False}), 500


@app.route("/auth/login/callback", methods=["POST"])
def auth_login_exchange():
    """Exchange the captured code for tokens."""
    try:
        if not auth._auth_code_event:
            return jsonify({"error": "No login flow in progress. Call /auth/login first."}), 400

        # Wait a bit for the callback if it hasn't arrived yet
        if not auth._auth_code_event.wait(timeout=30):
            return jsonify({"error": "Login timed out. Did you authorize in the browser?", "done": False}), 408

        if not auth._auth_code:
            return jsonify({"error": "Authorization failed or was denied.", "done": False}), 400

        auth.exchange_code(auth._auth_code, auth._auth_verifier or "")

        # Persist the refresh token to .env for future standalone use
        _save_refresh_token_to_env()

        return jsonify({
            "done": True,
            "email": auth.email,
            "message": "Authentication successful!",
        }), 200
    except Exception as e:
        return jsonify({"error": str(e), "done": False}), 500


def _save_refresh_token_to_env():
    """Save the refresh_token to .env file for future standalone runs."""
    try:
        env_path = Path(__file__).resolve().parent / ".env"
        if not env_path.exists():
            return
        content = env_path.read_text()
        token = auth._refresh_token
        if not token:
            return
        token_line = f"BRIDGE_REFRESH_TOKEN={token}"
        # Replace commented-out token or add new line
        if "BRIDGE_REFRESH_TOKEN=" in content or "#BRIDGE_REFRESH_TOKEN=" in content:
            new_content = []
            for line in content.splitlines():
                if "BRIDGE_REFRESH_TOKEN=" in line:
                    new_content.append(token_line)
                else:
                    new_content.append(line)
            env_path.write_text("\n".join(new_content) + "\n")
        else:
            env_path.write_text(content.rstrip() + "\n" + token_line + "\n")
        env_path.chmod(0o600)
        print("[auth] refresh_token saved to .env", file=sys.stderr)
    except Exception as e:
        print(f"[auth] warn saving token to .env: {e}", file=sys.stderr)


@app.route("/auth/login/status", methods=["GET"])
def auth_login_status():
    """Check auth status."""
    return jsonify({
        "authenticated": bool(auth._refresh_token),
        "email": auth.email,
        "project_id": auth._project_id,
        "in_progress": auth._auth_code_event is not None and not auth._auth_code_event.is_set(),
    })


@app.route("/login")
def login_page():
    """Interactive OAuth login page with dual mode:
    - Auto (local): opens browser, callback server on port 51121 captures code
    - Manual (remote): user pastes the redirect URL containing the auth code"""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Antigravity Bridge — Login</title>
<style>
  * { box-sizing: border-box; margin: 0; }
  body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #e6edf3; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
          padding: 40px; max-width: 580px; width: 100%; text-align: center; }
  h1 { font-size: 1.6rem; margin-bottom: 8px; }
  .sub { color: #8b949e; font-size: 0.9rem; margin-bottom: 24px; }
  button { background: #238636; color: white; border: none; border-radius: 6px;
           padding: 12px 24px; font-size: 1rem; cursor: pointer; margin: 8px; }
  button:hover { background: #2ea043; }
  button:disabled { opacity: 0.5; cursor: default; }
  .step { display: none; }
  .step.active { display: block; }
  .error { color: #f85149; margin-top: 12px; }
  .success { color: #3fb950; margin-top: 12px; }
  .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid #30363d;
             border-top-color: #58a6ff; border-radius: 50%; animation: spin 0.8s linear infinite;
             vertical-align: middle; margin-right: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .code-url { font-family: monospace; font-size: 0.8rem; color: #7b61ff; word-break: break-all;
              margin: 8px 0; padding: 8px; background: #0d1117; border-radius: 6px;
              border: 1px solid #30363d; text-align: left; }
  .code-url a { color: #58a6ff; }
  input[type="text"] { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #30363d;
                       background: #0d1117; color: #e6edf3; font-family: monospace; font-size: 0.85rem;
                       margin: 8px 0; }
  .manual-steps { text-align: left; font-size: 0.9rem; color: #8b949e; margin: 12px 0; }
  .manual-steps li { margin: 6px 0; }
  hr { border: none; border-top: 1px solid #30363d; margin: 20px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>🔑 Antigravity Bridge Login</h1>
  <p class="sub">Link your Google account to use Gemini Code Assist</p>

  <div id="step-check" class="step active">
    <p><span class="spinner"></span> Checking...</p>
  </div>

  <div id="step-start" class="step">
    <p>You need to link a Google account.</p>
    <button onclick="startAutoLogin()">Auto-Login (local browser)</button>

    <hr>
    <p style="color:#8b949e;font-size:0.85rem;">Or — paste the redirect URL manually:</p>
    <div class="manual-steps">
      <ol>
        <li>Click "Open Login Page" below</li>
        <li>In Google, authorize the app</li>
        <li>After redirect, copy the FULL URL from your browser's address bar</li>
        <li>Paste it below and click "Submit Code"</li>
      </ol>
    </div>
    <button onclick="openManualLogin()">Open Login Page →</button>
    <input type="text" id="manual-code" placeholder="Paste redirect URL here (starts with http://localhost...)">
    <button onclick="submitManualCode()">Submit Code</button>
    <div id="start-error" class="error"></div>
  </div>

  <div id="step-waiting" class="step">
    <p>A browser window should have opened for Google login.</p>
    <p style="margin-top: 16px;">
      <span class="spinner"></span> Waiting for authorization...
    </p>
  </div>

  <div id="step-done" class="step">
    <p class="success">✅ Authenticated!</p>
    <p id="done-email" style="margin: 8px 0; color: #8b949e;"></p>
    <button onclick="location.reload()">Check Again</button>
  </div>
</div>

<script>
let currentAuthUrl = '';

async function checkStatus() {
  try {
    const r = await fetch('/auth/login/status');
    const d = await r.json();
    if (d.authenticated) {
      show('step-done');
      document.getElementById('done-email').textContent = 'Email: ' + (d.email || 'unknown');
    } else {
      show('step-start');
    }
  } catch(e) { show('step-start'); }
}

async function startAutoLogin() {
  try {
    const r = await fetch('/auth/login', { method: 'POST' });
    const d = await r.json();
    if (d.error) { document.getElementById('start-error').textContent = d.error; return; }
    currentAuthUrl = d.auth_url;
    show('step-waiting');
    window.open(d.auth_url, '_blank');

    const poll = setInterval(async () => {
      try {
        const r2 = await fetch('/auth/login/callback', { method: 'POST' });
        const c = await r2.json();
        if (c.done) {
          clearInterval(poll);
          show('step-done');
          document.getElementById('done-email').textContent = 'Email: ' + (c.email || 'unknown');
        } else if (c.error && !c.error.includes('timed out') && !c.error.includes('No login flow')) {
          clearInterval(poll);
          document.getElementById('start-error').textContent = c.error;
          show('step-start');
        }
      } catch(e) {}
    }, 2000);
  } catch(e) {
    document.getElementById('start-error').textContent = e.message;
  }
}

async function openManualLogin() {
  try {
    const r = await fetch('/auth/login', { method: 'POST' });
    const d = await r.json();
    if (d.error) { document.getElementById('start-error').textContent = d.error; return; }
    currentAuthUrl = d.auth_url;
    window.open(d.auth_url, '_blank');
  } catch(e) {
    document.getElementById('start-error').textContent = e.message;
  }
}

async function submitManualCode() {
  const raw = document.getElementById('manual-code').value.trim();
  if (!raw) return;

  // Parse code from URL: http://localhost:51121/oauth-callback?code=XXX&state=YYY
  let code = null;
  try {
    const u = new URL(raw);
    code = u.searchParams.get('code');
  } catch(e) {
    // Maybe they pasted just the code
    code = raw;
  }
  if (!code) {
    document.getElementById('start-error').textContent = 'Could not extract code from URL. Paste the full redirect URL.';
    return;
  }

  try {
    const r = await fetch('/auth/login/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code })
    });
    const c = await r.json();
    if (c.done) {
      show('step-done');
      document.getElementById('done-email').textContent = 'Email: ' + (c.email || 'unknown');
    } else {
      document.getElementById('start-error').textContent = c.error || 'Unknown error';
    }
  } catch(e) {
    document.getElementById('start-error').textContent = e.message;
  }
}

function show(id) {
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}
checkStatus();
</script>
</body>
</html>"""


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
