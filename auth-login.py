#!/usr/bin/env python3
"""Interactive OAuth login for Antigravity Bridge — one command, no OpenCode."""

import sys
import json
import urllib.request
from urllib.parse import urlparse, parse_qs

BRIDGE_URL = "http://127.0.0.1:52848"


def step(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


# 1) Start login flow
step("Step 1 — Starting OAuth flow...")
try:
    req = urllib.request.Request(f"{BRIDGE_URL}/auth/login", method="POST")
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
except Exception as e:
    sys.exit(f"❌ Bridge not reachable: {e}")

if "error" in data:
    sys.exit(f"❌ {data['error']}")

auth_url = data["auth_url"]
print(f"✅ Login flow started (expires in {data.get('expires_in', 120)}s)")

# 2) Instructions
print()
print("┌──────────────────────────────────────────────────────────┐")
print("│                                                          │")
print("│  🔑 OPEN THIS LINK IN YOUR BROWSER:                      │")
print("│                                                          │")
print(f"│  {auth_url}")
print("│                                                          │")
print("│  1. Authorize the app in Google                          │")
print("│  2. After redirect, COPY the FULL URL from the bar       │")
print("│     (localhost:51121 will fail — that's OK)              │")
print("│  3. PASTE it below                                       │")
print("│                                                          │")
print("└──────────────────────────────────────────────────────────┘")
print()

# 3) Wait for paste
raw = input("Paste redirect URL: ").strip()

# 4) Extract code
try:
    parsed = urlparse(raw)
    code = parse_qs(parsed.query).get("code", [None])[0]
except Exception:
    code = raw  # maybe just the code

if not code:
    sys.exit("❌ Could not extract authorization code from URL. Paste the full redirect URL.")

# 5) Exchange
step("Step 2 — Exchanging code for tokens...")
body = json.dumps({"code": code}).encode()
req = urllib.request.Request(
    f"{BRIDGE_URL}/auth/login/manual",
    method="POST",
    data=body,
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
except Exception as e:
    sys.exit(f"❌ Token exchange failed: {e}")

if result.get("done"):
    print(f"\n✅ Authenticated!")
    print(f"   Email: {result.get('email', 'unknown')}")
    print(f"   Token saved to .env for future use")
else:
    print(f"\n❌ Failed: {result.get('error', 'Unknown error')}")
    sys.exit(1)
