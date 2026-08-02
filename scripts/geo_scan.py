#!/usr/bin/env python3
"""Geo-trades scan — DeItaone feed → Kalshi shortlist (7pm CST window).

Rule 18 (VJ 2026-08-02): geopolitical choke-point incidents (Hormuz, Suez,
straits) → oil ▲, gold ▲, VIX ▲, risk-OFF. De-escalation → inverse.
Analyze ONLY at 7pm CST (after-hours, esp Sunday PM — sets tone for week).

Pipeline:
  1. Pull DeItaone latest tweets (xurl, newest first)
  2. Classify: ESCALATION / DE-ESCALATION / NEUTRAL from keywords
  3. Map to trade direction: oil/gold/VIX up or down
  4. Pull Kalshi oil/gold/VIX shortlist, flag candidates

Feed source: xurl @DeItaone (installed, auth verified).
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

XURL = os.environ.get("XURL_BIN", "/data/.hermes/home/.local/bin/xurl")
HOME = "/data/.hermes/home"
DEITAONE_ID = "2704294333"

# --- geo classification ---
ESCALATE_KW = [
    "strike", "strikes", "attack", "attacks", "war", "missile", "missiles",
    "drone", "drones", "sanction", "sanctions", "seize", "seized", "blockade",
    "shutdown", "clos", "conflict", "military", "troops", "invasion",
    "escalat", "threaten", "threats", "nuclear", "ceasefire violated",
    "explosion", "explosions", "houthi", "strait", "chokepoint", "kill",
]
DEESCALATE_KW = [
    "deal", "ceasefire", "truce", "negotiation", "negotiations", "talks",
    "agreement", "delay", "delayed", "postpone", "postponed", "de-escalat",
    "deescalat", "call off", "calloff", "pullback", "withdraw", "diplomatic",
    "peace", "pause", "halt", "suspended", "suspend", "signal of friendship",
]
CHOKEPOINT_KW = [
    "hormuz", "suez", "bab el-mandeb", "strait", "chokepoint", "gulf",
    "red sea", "canal",
]

def classify(text: str) -> dict:
    t = text.lower()
    esc = [k for k in ESCALATE_KW if k in t]
    dee = [k for k in DEESCALATE_KW if k in t]
    choke = [k for k in CHOKEPOINT_KW if k in t]
    if esc and not dee:
        sent = "ESCALATION"
    elif dee and not esc:
        sent = "DE-ESCALATION"
    elif esc and dee:
        sent = "MIXED"
    else:
        sent = "NEUTRAL"
    return {"sentiment": sent, "escalate": esc[:5], "deescalate": dee[:5],
            "chokepoint": bool(choke), "choke_hits": choke[:3]}

def fetch_feed(n=20) -> list:
    """Pull DeItaone tweets via xurl raw API."""
    url = f"/2/users/{DEITAONE_ID}/tweets?max_results={n}&tweet.fields=created_at,public_metrics"
    env = dict(os.environ, HOME=HOME)
    r = subprocess.run([XURL, url], capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        return []
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return d.get("data", [])

def kalshi_get(path, params=None):
    """Minimal Kalshi GET (reuse predictor lib when run from repo)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from predictor import kalshi
        return kalshi.get_json(path, params=params, auth=True)
    except Exception:
        return None

def main():
    now_ct = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
    tweets = fetch_feed(20)
    if not tweets:
        print(f"[{now_ct} CT] GEO-SCAN: DeItaone feed unavailable (xurl/auth?)")
        return

    print(f"[{now_ct} CT] GEO-SCAN — DeItaone feed ({len(tweets)} tweets, newest first)")
    print("=" * 72)
    hits = []
    for tw in tweets:
        txt = tw.get("text", "").replace("\n", " ").strip()
        ts = tw.get("created_at", "")[:16]
        c = classify(txt)
        if c["sentiment"] != "NEUTRAL" or c["chokepoint"]:
            hits.append((tw, c, txt, ts))
            print(f"[{ts}] {c['sentiment']:<14} {txt[:110]}")
            if c["choke_hits"]:
                print(f"    choke-point: {', '.join(c['choke_hits'])}")

    print("=" * 72)
    # direction read — weight choke-point + recent tweets higher
    esc = sum(1 for _, c, _, _ in hits if c["sentiment"] == "ESCALATION")
    dee = sum(1 for _, c, _, _ in hits if c["sentiment"] == "DE-ESCALATION")
    choke_esc = sum(1 for _, c, _, _ in hits if c["sentiment"] == "ESCALATION" and c["chokepoint"])
    choke_dee = sum(1 for _, c, _, _ in hits if c["sentiment"] == "DE-ESCALATION" and c["chokepoint"])
    # recent 6 tweets carry more weight (fresh signal)
    recent = [c for tw, c, _, _ in hits[:6]]
    r_esc = sum(1 for c in recent if c["sentiment"] == "ESCALATION")
    r_dee = sum(1 for c in recent if c["sentiment"] == "DE-ESCALATION")

    score = (choke_dee - choke_esc) * 2 + (r_dee - r_esc)  # de-esc negative -> risk-on
    if score <= -2:
        direction = "RISK-OFF: oil ▲ gold ▲ VIX ▲ (choke-point escalation)"
    elif score >= 2:
        direction = "RISK-ON: oil ▼ gold ▼ VIX ▼ (de-escalation)"
    elif (r_dee + choke_dee) > (r_esc + choke_esc):
        direction = "RISK-ON bias: oil/gold/VIX soft (de-escalation lean)"
    elif (r_esc + choke_esc) > (r_dee + choke_dee):
        direction = "RISK-OFF bias: oil/gold/VIX firm (escalation lean)"
    else:
        direction = "NEUTRAL — no clear geo signal"
    print(f"DIRECTION: {direction}")

    # Kalshi shortlist (oil/gold/VIX)
    print("\nKALSHI SHORTLIST (for geo trade direction):")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from predictor import kalshi
        for series, label in [("KXWTI", "WTI"), ("KXGOLDD", "GOLD daily"), ("KXGOLDMON", "GOLD monthly")]:
            d = kalshi.get_json("/markets", params={"series_ticker": series, "status": "open", "limit": 100}, auth=True)
            ms = [m for m in (d or {}).get("markets") or [] if m.get("market_type") == "binary"]
            # nearest 3 open events by close time
            ms.sort(key=lambda m: m.get("close_time", ""))
            seen = set()
            n = 0
            for m in ms:
                ev = m["ticker"].split("-T")[0]
                if ev in seen:
                    continue
                seen.add(ev)
                bid = float(m.get("yes_bid_dollars") or 0)
                ask = float(m.get("yes_ask_dollars") or 0)
                print(f"  {label} {m['ticker'][:46]:46s} bid={bid:.2f} ask={ask:.2f} close={m.get('close_time','')[:10]}")
                n += 1
                if n >= 4:
                    break
    except Exception as e:
        print(f"  Kalshi pull failed: {e}")

if __name__ == "__main__":
    main()
