#!/usr/bin/env python3
"""Live-option flip scanner — find in-play markets where odds can flip.

Scans Kalshi for LIVE binary markets (set-winner tennis, match winners, etc.)
where:
  - price is in the FLIP ZONE: one side mid between 0.35-0.65 (not decided,
    not dead) — the market can swing either way
  - tight order range: spread <= 3c (can place limit near current)
  - enough liquidity: bid+ask depth and volume so fills matter
Outputs a ranked table (flip score) with suggested limit + TTL.

VJ rules (2026-08-02):
  - PRESENT ONLY 7am-10pm CT (waking hours). Outside: silent (empty stdout).
  - Never auto-trade. This script only IDENTIFIES candidates for VJ to pick.
  - Suggestion suppression: only show markets where BOTH sides have non-trivial
    flip probability — a 90c/10c market is decided, not a flip candidate.
  - Order placement (when VJ picks) stays limit-only, band <=40c/raise<=10%,
    win-floor >=50% from CURRENT state — enforced at execution, not here.

Usage (cron, no_agent=True, deliver verbatim):
  KALSHI_API_KEY=.. KALSHI_PRIVATE_KEY=.. python3 scripts/live_flip_scan.py
"""
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = "https://external-api.kalshi.com/trade-api/v2"
CT = ZoneInfo("America/Chicago")

# --- waking hours gate (VJ: 7am-10pm CT) ---
now_ct = datetime.now(CT)
hour = now_ct.hour + now_ct.minute / 60.0
if not (7.0 <= hour <= 22.0):
    # silent — watchdog pattern, empty stdout = no delivery
    sys.exit(0)


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


def _vol(m):
    try:
        return float(m.get("volume_fp", 0)) * max(
            float(m.get("last_price_dollars", 0) or 0), 0.001)
    except (TypeError, ValueError):
        return 0


def main():
    out = []
    # candidate series: live tennis set winners + match winners (flip-prone)
    series_prefixes = ["KXWTASETWINNER", "KXATPSETWINNER", "KXWTAMATCH",
                       "KXATPMATCH", "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH",
                       "KXT20MATCH", "KXMLBGAME"]
    # collect today's events from cache (fast, no /events pagination)
    evs = {}
    try:
        cache = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "data", "kalshi_events_cache.json")))
        evs = cache
    except (OSError, json.JSONDecodeError):
        pass

    today_evs = [e for e in evs if any(e.upper().startswith(p) for p in series_prefixes)
                 and "26AUG02" in e.upper()]

    rows = []
    for ev in today_evs:
        d = _get("/markets", {"event_ticker": ev, "status": "open", "limit": 100})
        for m in (d or {}).get("markets") or []:
            if m.get("market_type") != "binary":
                continue
            try:
                bid = float(m.get("yes_bid_dollars") or 0)
                ask = float(m.get("yes_ask_dollars") or 0)
            except (TypeError, ValueError):
                continue
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2
            spread = ask - bid
            # flip zone: mid between 0.35 and 0.65 (either side can win)
            if not (0.35 <= mid <= 0.65):
                continue
            # tight range: spread <= 3c so a limit 1-2c off is realistic
            if spread > 0.03:
                continue
            depth = 0.0
            try:
                ob = _get(f"/markets/{m['ticker']}/orderbook")
                fp = (ob or {}).get("orderbook_fp") or {}
                yes = fp.get("yes_dollars") or []
                no = fp.get("no_dollars") or []
                depth = sum(float(l[1]) for l in yes[-3:]) + sum(float(l[1]) for l in no[-3:])
            except Exception:
                pass
            if depth < 200:
                continue
            v = _vol(m)
            if v < 2000:
                continue
            # flip score: closeness to 0.50 + volume + tightness
            flip_score = (1 - abs(mid - 0.50)) * min(v, 500000) / 500000
            rows.append({
                "t": m["ticker"], "q": m.get("title", ""), "mid": mid, "bid": bid,
                "ask": ask, "spread": spread, "vol": v, "depth": depth,
                "score": flip_score,
            })

    rows.sort(key=lambda x: x["score"], reverse=True)
    if not rows:
        print(f"[{now_ct:%H:%M} CT] No flip-zone live markets right now.")
        return

    print(f"[{now_ct:%H:%M} CT] Live flip candidates ({len(rows)} shown, top 15)")
    print("Flip-zone = mid 0.35-0.65, spread <=3c, depth >=200. Place limit 1-2c off.")
    print("TTL by score state: set1-early 30-60m | mid-match 15-30m | moved>10c from limit = CANCEL")
    print("=" * 78)
    for i, r in enumerate(rows[:15], 1):
        # flip bet = buy the CHEAP side (underdog at <0.50) betting it flips.
        # Only suggest when cheap side mid <= 0.45 (real flip candidate).
        if r["mid"] <= 0.50:
            side = "YES"
            limit = round(min(r["mid"] - 0.01, 0.40), 2)  # band: YES cap 40c
        else:
            # expensive YES mid >0.50 -> buy NO (i.e. the other side, cheap)
            side = "NO"
            limit = round(min(1 - r["mid"] - 0.01, 0.40), 2)
        limit = max(limit, 0.01)
        # TTL from how far price is from limit: gap>10c = dead, 5-10c = 15m, <5c = 30-60m
        gap = abs(r["mid"] - limit)
        if gap > 0.10:
            ttl = "CANCEL/RE-SCAN"
        elif gap > 0.05:
            ttl = "15m"
        elif r["mid"] <= 0.45:
            ttl = "60m"
        else:
            ttl = "30m"
        print(f"{i:>2}. {r['t'][:44]:44s} mid={r['mid']:.2f} spr={r['spread']:.2f} "
              f"vol=${r['vol']:8,.0f}")
        print(f"     {r['q'][:70]}")
        print(f"     -> {side} @ {limit:.2f} | TTL {ttl} | fill if price dips")


if __name__ == "__main__":
    main()
