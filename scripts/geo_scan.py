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
# VJ 2026-08-02: the biggest market mover = market-moving tweets from the
# US PRESIDENT (Trump), referenced via DeItaone feed. Trump statements carry
# outsized weight: ceasefire/deal = oil/commodities ease; strike/threat =
# oil/gold/VIX spike; tariffs/trade = commerce/commodities.
TRUMP_MARKERS = ["trump", "president"]
TRUMP_ESC = ["strike", "strikes", "attack", "war", "missile", "tariff", "tariffs", "sanction", "sanctions", "punish", "punishment"]
TRUMP_DEESC = ["ceasefire", "deal", "negotiation", "negotiations", "talks", "agreement", "delay", "delayed", "postpone", "postponed", "peace", "call off", "calloff", "friendship", "de-escalat", "deescalat"]
TRUMP_TRADE = ["tariff", "tariffs", "trade", "commerce", "china", "europe", "import", "export"]

def classify(text: str) -> dict:
    t = text.lower()
    esc = [k for k in ESCALATE_KW if k in t]
    dee = [k for k in DEESCALATE_KW if k in t]
    choke = [k for k in CHOKEPOINT_KW if k in t]
    # Trump detection (VJ: biggest market mover — US president statements)
    is_trump = any(k in t for k in TRUMP_MARKERS)
    trump_esc = [k for k in TRUMP_ESC if k in t]
    trump_deesc = [k for k in TRUMP_DEESC if k in t]
    trump_trade = [k for k in TRUMP_TRADE if k in t]
    if esc and not dee:
        sent = "ESCALATION"
    elif dee and not esc:
        sent = "DE-ESCALATION"
    elif esc and dee:
        sent = "MIXED"
    else:
        sent = "NEUTRAL"
    # Trump override: his explicit words win over keyword ambiguity
    if is_trump:
        if trump_esc and not trump_deesc:
            sent = "TRUMP-ESCALATION"
        elif trump_deesc and not trump_esc:
            sent = "TRUMP-DE-ESCALATION"
        elif trump_deesc and trump_esc:
            sent = "TRUMP-MIXED"
        elif trump_trade:
            sent = "TRUMP-TRADE"
    return {"sentiment": sent, "escalate": esc[:5], "deescalate": dee[:5],
            "chokepoint": bool(choke), "choke_hits": choke[:3],
            "is_trump": is_trump, "trump_esc": trump_esc[:5],
            "trump_deesc": trump_deesc[:5], "trump_trade": trump_trade[:5]}

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

def _repo_path():
    """Predictor repo root — works from repo copy AND cron copy
    (~/.hermes/scripts/geo_scan.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    # cron copy: ~/.hermes/scripts -> look for ../.. == /data/.hermes, not repo
    if here.endswith("scripts") and os.path.basename(os.path.dirname(here)) == ".hermes":
        repo = "/data/workspace/predictor"
        if os.path.isdir(os.path.join(repo, "predictor")):
            return repo
        return None
    # repo copy: <repo>/scripts -> parent is repo
    return os.path.dirname(here)

def kalshi_get(path, params=None):
    """Minimal Kalshi GET (reuse predictor lib when run from repo)."""
    repo = _repo_path()
    if not repo:
        return None
    try:
        sys.path.insert(0, repo)
        from predictor import kalshi
        return kalshi.get_json(path, params=params, auth=True)
    except Exception:
        return None

def main():
    # Rule 18: geo analysis ONLY 7pm-8pm CT. Silent otherwise (watchdog pattern).
    now = datetime.now().astimezone()
    try:
        from zoneinfo import ZoneInfo
        ct = now.astimezone(ZoneInfo("America/Chicago"))
    except Exception:
        ct = now
    if not (19 <= ct.hour < 20):
        # outside window — silent (no stdout = no delivery for no_agent cron)
        return
    now_ct = ct.strftime("%H:%M")
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
            star = "★" if c["is_trump"] else " "
            print(f"[{ts}]{star} {c['sentiment']:<18} {txt[:105]}")
            if c["choke_hits"]:
                print(f"    choke-point: {', '.join(c['choke_hits'])}")

    print("=" * 72)
    # direction read — Trump statements are the BIGGEST mover (VJ 2026-08-02):
    # his ceasefire/deal words cool oil/commodities; strike/tariff words spike
    # them. Weight Trump 3x. Recent tweets (first 6) carry extra weight.
    esc = sum(1 for _, c, _, _ in hits if c["sentiment"] == "ESCALATION")
    dee = sum(1 for _, c, _, _ in hits if c["sentiment"] == "DE-ESCALATION")
    choke_esc = sum(1 for _, c, _, _ in hits if c["sentiment"] == "ESCALATION" and c["chokepoint"])
    choke_dee = sum(1 for _, c, _, _ in hits if c["sentiment"] == "DE-ESCALATION" and c["chokepoint"])
    # recent 6 tweets carry more weight (fresh signal)
    recent = [c for tw, c, _, _ in hits[:6]]
    r_esc = sum(1 for c in recent if c["sentiment"] == "ESCALATION")
    r_dee = sum(1 for c in recent if c["sentiment"] == "DE-ESCALATION")

    # Trump-weighted score (3x)
    t_esc = sum(3 for _, c, _, _ in hits if c["sentiment"] == "TRUMP-ESCALATION")
    t_dee = sum(3 for _, c, _, _ in hits if c["sentiment"] == "TRUMP-DE-ESCALATION")
    t_trade = sum(2 for _, c, _, _ in hits if c["sentiment"] == "TRUMP-TRADE")
    t_mixed = sum(1 for _, c, _, _ in hits if c["sentiment"] == "TRUMP-MIXED")

    score = (choke_dee - choke_esc) * 2 + (r_dee - r_esc) + (t_dee - t_esc) + (t_trade - t_mixed)
    if score <= -2:
        direction = "RISK-OFF: oil ▲ gold ▲ VIX ▲ (choke-point/Trump escalation)"
    elif score >= 2:
        direction = "RISK-ON: oil ▼ gold ▼ VIX ▼ (de-escalation/Trump deal)"
    elif (r_dee + choke_dee + t_dee) > (r_esc + choke_esc + t_esc):
        direction = "RISK-ON bias: oil/gold/VIX soft (de-escalation lean)"
    elif (r_esc + choke_esc + t_esc) > (r_dee + choke_dee + t_dee):
        direction = "RISK-OFF bias: oil/gold/VIX firm (escalation lean)"
    else:
        direction = "NEUTRAL — no clear geo signal"
    print(f"DIRECTION: {direction}")

    # Kalshi shortlist (oil/gold/VIX)
    print("\nKALSHI SHORTLIST (for geo trade direction):")
    try:
        repo = _repo_path()
        if repo:
            sys.path.insert(0, repo)
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
