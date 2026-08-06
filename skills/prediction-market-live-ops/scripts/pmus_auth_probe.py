#!/usr/bin/env python3
"""pmus_auth_probe.py — deterministic Polymarket US auth check.

Verifies the Ed25519 header signing works against the live API without
exposing any secret. Reads POLYMARKET_API_KEY / POLYMARKET_SECRET_KEY from
/data/.hermes/.env (or already-set env). Prints status + endpoint reachability.
Exit 0 = auth OK, non-zero = broken.

Usage:
  python3 pmus_auth_probe.py            # full check
  python3 pmus_auth_probe.py --quick    # positions only
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

AUTH_BASE = "https://api.polymarket.us"
PUBLIC_BASE = "https://gateway.polymarket.us"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _load_env() -> None:
    for p in ("/data/.hermes/.env", os.path.expanduser("~/.hermes/.env")):
        if os.path.isfile(p):
            for line in open(p):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _auth_headers(method: str, path: str) -> dict:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    key_id = os.environ.get("POLYMARKET_API_KEY", "")
    secret = os.environ.get("POLYMARKET_SECRET_KEY", "")
    ts = str(int(time.time() * 1000))
    message = f"{ts}{method}{path}"
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
    sig = base64.b64encode(priv.sign(message.encode())).decode()
    return {"User-Agent": UA, "Accept": "application/json",
            "X-PM-Access-Key": key_id, "X-PM-Timestamp": ts,
            "X-PM-Signature": sig, "Content-Type": "application/json"}


def _get(url: str, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="positions only")
    args = ap.parse_args()
    _load_env()

    key_id = os.environ.get("POLYMARKET_API_KEY", "")
    secret = os.environ.get("POLYMARKET_SECRET_KEY", "")
    if not key_id or not secret:
        print("FAIL: POLYMARKET_API_KEY / POLYMARKET_SECRET_KEY missing")
        return 1
    print(f"keys present: key_id len={len(key_id)} secret len={len(secret)}")

    # auth check (the thing that usually breaks)
    st, body = _get(AUTH_BASE + "/v1/portfolio/positions", _auth_headers("GET", "/v1/portfolio/positions"))
    if st == 200:
        data = json.loads(body)
        n = len(data.get("positions") or {})
        print(f"OK auth: GET /v1/portfolio/positions 200 ({n} positions)")
    elif st == 403 and "1010" in body:
        print("FAIL auth: 403 error code 1010 = Cloudflare bot block — add browser UA")
        return 1
    else:
        print(f"FAIL auth: HTTP {st}: {body[:200]}")
        return 1

    if args.quick:
        return 0

    # balance + public reads
    st, body = _get(AUTH_BASE + "/v1/account/balances", _auth_headers("GET", "/v1/account/balances"))
    print(f"balances: HTTP {st} ({body[:120]})")
    st, body = _get(PUBLIC_BASE + "/v1/markets?closed=false&limit=1", {"User-Agent": UA, "Accept": "application/json"})
    print(f"public markets: HTTP {st} ({'markets' in body})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
