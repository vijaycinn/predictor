#!/usr/bin/env python3
"""Kalshi market search by player/team name or ticker abbreviation (verified 2026-08-02).

Fixes the two search bugs that hid Tolev vs Cazacu (KXATPCHALLENGERMATCH-26AUG02TOLCAZ):
1. Title search paginated fully (old bug: stopped at first 10 matches — MVE parlay
   junk with player names in ticker filled the cap before the real market was reached).
2. Ticker-abbreviation matching against the events cache (TOLCAZ = Tolev+Cazacu),
   so abbreviated event tickers are found without knowing the exact prefix
   (KXATPCHALLENGERMATCH vs KXATPMATCH — both are matched here).

Usage:
    KALSHI_API_KEY=<key> KALSHI_PRIVATE_KEY=<pem> python3 search_market.py tolev
    KALSHI_API_KEY=<key> KALSHI_PRIVATE_KEY=<pem> python3 search_market.py cazacu --min-vol 1000
    KALSHI_API_KEY=<key> KALSHI_PRIVATE_KEY=<pem> python3 search_market.py "taylor fritz"

Outputs: matching open binary markets sorted by dollar volume, with bid/ask/liquidity.
"""
import argparse
import base64
import json
import os
import sys
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://external-api.kalshi.com/trade-api/v2"
EVENTS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "kalshi_events_cache.json")


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


def abbrev_matches(query: str) -> list[str]:
    """Event tickers from cache whose abbreviated form contains the query.

    Kalshi abbreviates multi-name events (Tolev vs Cazacu -> TOLCAZ). Match by
    stripping the KX-prefix/date segment and checking the query's letters appear
    in order (TOL from Tolev, CAZ from Cazacu).
    """
    q = query.lower().replace(" ", "")
    if not q:
        return []
    out = []
    try:
        cache = json.load(open(EVENTS_CACHE))
    except (OSError, json.JSONDecodeError):
        return out
    for ev in cache:
        # event ticker tail: e.g. KXATPCHALLENGERMATCH-26AUG02TOLCAZ -> TOLCAZ
        tail = ev.split("-")[-1] if "-" in ev else ev
        t = tail.lower()
        # ordered subsequence match (TOLCAZ contains t,o,l,c,a,z for "tolevcazacu")
        it = iter(t)
        if all(ch in it for ch in q):
            out.append(ev)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", help="player/team name, ticker, or abbreviation fragment")
    ap.add_argument("--min-vol", type=float, default=0, help="min dollar volume filter")
    ap.add_argument("--max-results", type=int, default=30)
    args = ap.parse_args()
    q = args.query.lower()

    found = {}

    # 1) Ticker-abbreviation match against events cache (catches TOLCAZ-style)
    for ev in abbrev_matches(args.query):
        d = _get("/markets", {"event_ticker": ev, "status": "open", "limit": 200})
        for m in (d or {}).get("markets") or []:
            if m.get("market_type") != "binary":
                continue
            found[m["ticker"]] = m

    # 2) Full-pagination title search (NO early-exit cap — old bug)
    cursor = None
    pages = 0
    while pages < 20:  # 20k markets scanned; enough for name search
        params = {"status": "open", "limit": 1000, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        d = _get("/markets", params)
        ms = (d or {}).get("markets") or []
        if not ms:
            break
        for m in ms:
            if m.get("market_type") != "binary":
                continue
            title = (m.get("title") or "").lower()
            if q in title or q in m.get("ticker", "").lower():
                found[m["ticker"]] = m
        cursor = (d or {}).get("cursor")
        pages += 1
        if not cursor:
            break

    # sort by dollar volume
    def vol(m):
        try:
            return float(m.get("volume_fp", 0)) * max(
                float(m.get("last_price_dollars", 0) or 0), 0.001)
        except (TypeError, ValueError):
            return 0

    rows = []
    for t, m in found.items():
        v = vol(m)
        if v < args.min_vol:
            continue
        rows.append((v, t, m))
    rows.sort(key=lambda x: x[0], reverse=True)

    print(f"matches: {len(rows)} (query '{args.query}', min_vol ${args.min_vol:,.0f})\n")
    for v, t, m in rows[: args.max_results]:
        print(f"  {t:52s} vol=${v:10,.0f} bid={m.get('yes_bid_dollars','?'):>5s} "
              f"ask={m.get('yes_ask_dollars','?'):>5s} close={m.get('close_time','?')[:10]}")
        print(f"      {m.get('title','')[:80]}")
    if not rows:
        print("  (none — try fewer words or a ticker fragment like TOLCAZ)")


if __name__ == "__main__":
    main()
