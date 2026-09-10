#!/usr/bin/env python3
"""Interactive OAuth login for Antigravity Bridge.

Standalone by default: performs the Google OAuth (PKCE) flow directly and writes
BRIDGE_REFRESH_TOKEN into .env (preserving every other line). The bridge does NOT
need to be running. Use --bridge URL to go through a running bridge instead
(useful for multi-account: --bridge http://127.0.0.1:52847 --account sk-xxx).

Env / .env: ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_CLIENT_SECRET (required).
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:51121/oauth-callback"
# Must match server.py Auth.SCOPES (aicode is required by daily-cloudcode-pa since 2026-09)
SCOPES = (
    "openid "
    "https://www.googleapis.com/auth/aicode "
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile "
    "https://www.googleapis.com/auth/cclog "
    "https://www.googleapis.com/auth/experimentsandconfigs"
)


def step(msg: str) -> None:
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


def load_dotenv(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def upsert_env(path: Path, key: str, value: str) -> None:
    """Set key=value in .env, replacing an existing line or appending. Keeps everything else."""
    lines = path.read_text().splitlines() if path.exists() else []
    done = False
    for i, l in enumerate(lines):
        if l.startswith(f"{key}=") or l.startswith(f"export {key}="):
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def show_link_box(auth_url: str) -> None:
    print("\n┌──────────────────────────────────────────────────────────┐")
    print("│  🔑 OPEN THIS LINK IN YOUR BROWSER:                      │")
    print("│                                                          │")
    print(f"│  {auth_url}")
    print("│                                                          │")
    print("│  1. Authorize the app in Google                          │")
    print("│  2. After redirect, COPY the FULL URL from the bar       │")
    print("│     (localhost:51121 will fail — that's OK)              │")
    print("│  3. PASTE it below                                       │")
    print("└──────────────────────────────────────────────────────────┘\n")


def code_from_redirect(redirect: str) -> str:
    redirect = redirect.strip()
    if redirect.startswith("http"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
        code = (qs.get("code") or [""])[0]
    else:
        code = redirect  # user pasted only the code
    if not code:
        sys.exit("❌ No 'code' found in what you pasted.")
    return code


# ── Standalone flow (no bridge needed) ─────────────────────────
def standalone() -> None:
    env = {**load_dotenv(ENV_PATH), **{k: v for k, v in os.environ.items() if k.startswith("ANTIGRAVITY_")}}
    client_id = env.get("ANTIGRAVITY_CLIENT_ID", "")
    client_secret = env.get("ANTIGRAVITY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        sys.exit("❌ ANTIGRAVITY_CLIENT_ID / ANTIGRAVITY_CLIENT_SECRET missing. Put them in .env first (see .env.example).")

    step("Step 1 — Building OAuth URL (PKCE)...")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    show_link_box(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")
    code = code_from_redirect(input("Paste redirect URL: "))

    step("Step 2 — Exchanging code for tokens...")
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        tok = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        sys.exit(f"❌ Token exchange failed: {e.code} {e.read().decode(errors='replace')[:400]}")
    if "refresh_token" not in tok:
        sys.exit(f"❌ No refresh_token in response: {list(tok.keys())}")

    email = "?"
    if "id_token" in tok:
        try:
            p = tok["id_token"].split(".")[1]
            p += "=" * ((4 - len(p) % 4) % 4)
            email = json.loads(base64.urlsafe_b64decode(p)).get("email", "?")
        except Exception:
            pass
    upsert_env(ENV_PATH, "BRIDGE_REFRESH_TOKEN", tok["refresh_token"])
    print(f"\n✅ Authenticated!\n   Email: {email}\n   Scopes: {tok.get('scope', '?')}\n   BRIDGE_REFRESH_TOKEN saved to {ENV_PATH}")


# ── Bridge flow (server running; supports multi-account) ───────
def via_bridge(bridge: str, account, admin_key) -> None:
    def call(path: str, body=None):
        headers = {"Content-Type": "application/json"}
        if admin_key:
            headers["Authorization"] = f"Bearer {admin_key}"
        req = urllib.request.Request(f"{bridge}{path}", method="POST",
                                     data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            sys.exit(f"❌ {path}: HTTP {e.code} {e.read().decode(errors='replace')[:400]}")
        except Exception as e:
            sys.exit(f"❌ Bridge not reachable at {bridge}: {e}")

    step(f"Step 1 — Starting OAuth flow via {bridge}...")
    data = call(f"/admin/accounts/{account}/login" if account else "/auth/login")
    if "error" in data:
        sys.exit(f"❌ {data['error']}")
    show_link_box(data["auth_url"])
    redirect = input("Paste redirect URL: ")
    step("Step 2 — Exchanging code for tokens...")
    res = call("/auth/login/manual", {"code": code_from_redirect(redirect)})
    if "error" in res:
        sys.exit(f"❌ {res['error']}")
    print(f"\n✅ Authenticated!\n   Email: {res.get('email', '?')}\n   Account: {account or 'default'} (stored by the bridge)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bridge", help="Use a running bridge instead of the standalone flow, e.g. http://127.0.0.1:52847")
    ap.add_argument("--account", help="(with --bridge) api_key of the account to log in (multi-account)")
    ap.add_argument("--admin-key", default=os.environ.get("BRIDGE_ADMIN_KEY"), help="(with --bridge) BRIDGE_ADMIN_KEY")
    args = ap.parse_args()
    if args.bridge:
        via_bridge(args.bridge.rstrip("/"), args.account, args.admin_key)
    else:
        standalone()
