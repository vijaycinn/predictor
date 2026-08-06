#!/usr/bin/env python3
"""Category-targeted Kalshi market discovery (verified 2026-08-02).

Workaround for the predictor scan pipeline starving non-sports categories
(`discover_markets` caps at max_markets=40 and /markets pagination returns
sports first — crypto/econ never reached despite config listing them).

Usage:
    KALSHI_API_KEY=<key> KALSHI_PRIVATE_KEY=<pem> \
        python3 category_scan.py crypto econ mlb

Prints top markets per category by dollar volume (binary only).
"""
import base64
import json
import os
import sys
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://external-api.kalshi.com/trade-api/v2"


def _sign(ts, method, path):
    msg = f"{ts}{method}{path}".encode()
    key = serialization.load_pem_private_key(
        os.environ["KALSHI_PRIVATE_KEY"].encode(), password=None)
    sig = key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def _get(path, params=None):
    ts = str(int(time.time() * 1000))
    headers = {
        "KALSHI-API-KEY": os.environ["KALSHI_API_KEY"],
        "KALSHI-TIMESTAMP": ts,
        "KALSHI-SIGNATURE": _sign(ts, "GET", path),
    }
    r = requests.get(BASE + path, params=params, headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def series_categories():
    """series_ticker -> set(category strings), from /events pagination."""
    out = {}
    cursor = None
    while True:
        params = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        d = _get("/events", params)
        if not d:
            break
        evs = d.get("events") or []
        if not evs:
            break
        for e in evs:
            s = e.get("series_ticker") or ""
            if s:
                out.setdefault(s, set()).add((e.get("category") or "").lower())
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def fetch_series(series_list, limit_series=25):
    out = []
    for s in series_list[:limit_series]:
        d = _get("/markets", {"series_ticker": s, "status": "open", "limit": 500})
        for m in (d or {}).get("markets") or []:
            if m.get("market_type") != "binary":
                continue
            try:
                vol = float(m.get("volume_fp", 0)) * max(
                    float(m.get("last_price_dollars", 0) or 0), 0.001)
            except (TypeError, ValueError):
                vol = 0
            m["_vol_usd"] = vol
            out.append(m)
    out.sort(key=lambda x: x["_vol_usd"], reverse=True)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cats = sys.argv[1:]
    sc = series_categories()
    print(f"series mapped: {len(sc)}")

    def match(s, keys):
        return any(any(k in c for k in keys) for c in sc.get(s, set()))

    cat_keys = {
        "crypto": ["crypto", "digital"],
        "econ": ["econom", "financ", "market", "inflation", "fed", "rate",
                 "job", "gdp", "unemploy", "cpi", "ppi"],
        "mlb": ["baseball"],
    }
    for cat in cats:
        if cat == "mlb":
            series = sorted(s for s in sc if s.upper().startswith("KXMLB"))
        else:
            keys = cat_keys.get(cat, [cat])
            series = [s for s, cs in sc.items() if match(s, keys)]
        mkts = fetch_series(series)
        print(f"\n=== {cat}: {len(series)} series, {len(mkts)} binary markets, top 12 ===")
        for m in mkts[:12]:
            print(f"  {m['ticker']:46s} vol=${m['_vol_usd']:9.0f} "
                  f"px={m.get('last_price_dollars','?'):>5s} "
                  f"bid={m.get('yes_bid_dollars','?'):>5s} "
                  f"ask={m.get('yes_ask_dollars','?'):>5s} "
                  f"close={m.get('close_time','?')[:10]}")


if __name__ == "__main__":
    main()
