#!/usr/bin/env python3
"""Tier 1 fast loop — runs every 30m, $0 LLM cost (no agent).

Does: order lifecycle reconcile (fills/cancels), PMXT arb feed check,
market resolution tracking. Prints ONLY when something needs attention
(empty stdout = silent; no_agent cron delivers verbatim).

Config: risk.max_open_positions caps concurrent open positions.
"""
import json
import sys
from pathlib import Path

# predictor project root — script may live in ~/.hermes/scripts (cron) or project scripts/
_PROJECT = Path("/data/workspace/predictor")
if _PROJECT.exists():
    sys.path.insert(0, str(_PROJECT))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from predictor import db, executor as executor_mod, learn, pmxt  # noqa: E402
from predictor.config import load_config  # noqa: E402

CFG = load_config(str(_PROJECT / "config.yaml")) if _PROJECT.exists() else load_config()
DB_DIR = _PROJECT / "data" if _PROJECT.exists() else Path(__file__).resolve().parent.parent / "data"
MIN_ARB_NET = 0.02  # only surface arbs clearing 2c net

out_lines = []

# --- 1. Order lifecycle reconcile (paper; live uses exchange reconcile) ---
for venue, dbfile in (("polymarket", "predictor.db"), ("kalshi", "kalshi.db")):
    dbp = DB_DIR / dbfile
    if not dbp.exists():
        continue
    cfg = dict(CFG)
    cfg["venue"] = venue
    conn = db.connect(dbp)
    try:
        events = executor_mod.reconcile_orders(conn, cfg)
    except Exception as e:
        out_lines.append(f"[{venue}] reconcile error: {e}")
        conn.close()
        continue
    for ev in events:
        row = conn.execute("SELECT question FROM markets WHERE condition_id=?", (ev.get("condition_id", ""),)).fetchone()
        q = row["question"][:45] if row else ev.get("condition_id", "")[:20]
        out_lines.append(f"[{venue}] order #{ev['trade_id']} {ev['event']}" + (f" @ {ev['fill_price']:.3f}" if ev.get("fill_price") else "") + f" | {q}")
    # position cap status
    cap = cfg.get("risk", {}).get("max_open_positions", 5)
    n_open = len(db.open_positions(conn))
    if n_open >= cap:
        out_lines.append(f"[{venue}] POSITION CAP {n_open}/{cap} reached — no new trades until close/resolution")
    conn.close()

# --- 2. PMXT arb feed (only kalshi-leg + clear-net arbs) ---
# Primary: PMXT Router (16 venues). Fallback: Predexon Kalshi->Polymarket
# matcher (arb.py) when PMXT flakes — it does, intermittently.
arb_source = "pmxt"
try:
    res = pmxt.ranked_opportunities(min_net_edge=MIN_ARB_NET, limit=10)
    if not res.get("opportunities") and not res.get("total_arbs"):
        raise ValueError("empty pmxt arb feed")
except Exception as e:
    # fallback to Predexon matcher
    arb_source = f"predexon (pmxt failed: {str(e)[:50]})"
    try:
        from predictor import arb, predexon as predexon_mod
        if predexon_mod.health():
            predexon_res = arb.arb_check(CFG, min_volume=3000, limit=20)
            res = {
                "opportunities": [
                    {
                        "kalshi_ticker": None,
                        "buy_venue": "kalshi", "sell_venue": "polymarket",
                        "buy_price": o["best"]["buy_a"]["price"], "sell_price": o["best"]["buy_b"]["price"],
                        "net_edge": o["best"]["net_edge"], "net_edge_pct": o["best"]["net_edge_pct"],
                        "title_a": o["kalshi_market"].get("title", ""),
                        "validation": f"predexon match {o['confidence']}: {o['match_reason']}",
                    }
                    for o in predexon_res.get("positive", [])
                ],
                "total_arbs": len(predexon_res.get("positive", [])),
            }
        else:
            raise ValueError("predexon unhealthy")
    except Exception as e2:
        out_lines.append(f"[ARB] both feeds failed (pmxt: {str(e)[:40]}, predexon: {str(e2)[:40]})")
        res = {"opportunities": [], "total_arbs": 0}

# EXECUTABLE LEGS ONLY (VJ 2026-08-06): tradeable venues = kalshi + polymarket_us.
# PM.com = reference/truth only; myriad/limitless/etc = discovery only. An arb
# whose SELL leg sits on a non-executable venue is NOT tradeable — surfacing it
# is noise that led to a wrong impression (hit live: buy kalshi sell myriad).
# Rule 9: arb = SELL-ONLY ON KALSHI where possible; at minimum BOTH legs must
# be executable.
EXEC_VENUES = {"kalshi", "polymarket_us", "polymarket_usd"}
kalshi_exec = [
    o for o in res.get("opportunities", [])
    if o.get("kalshi_ticker")
    and str(o.get("sell_venue", "")).lower() in EXEC_VENUES
    and str(o.get("buy_venue", "")).lower() in EXEC_VENUES
]
if kalshi_exec:
    for o in kalshi_exec[:3]:
        out_lines.append(
            f"[ARB:{arb_source[:8]}] {o['net_edge']*100:.2f}% EXECUTABLE K={o['kalshi_ticker']} "
            f"buy {o['buy_venue']}@{o['buy_price']:.3f} sell {o['sell_venue']}@{o['sell_price']:.3f} | {o['title_a'][:35]}"
        )
# discovery-only arbs (non-executable sell leg — myriad/polymarket.com/others)
# are NOT delivered — VJ rule: suppress non-actionable noise. Silent unless a
# fully-executable trade exists.

# --- 3. Resolution tracking ---
for venue, dbfile in (("polymarket", "predictor.db"), ("kalshi", "kalshi.db")):
    dbp = DB_DIR / dbfile
    if not dbp.exists():
        continue
    conn = db.connect(dbp)
    try:
        resolved = learn.check_resolutions(conn)
    except Exception:
        resolved = []
        conn.close()
        continue
    for r in resolved:
        out_lines.append(f"[{venue}] RESOLVED {r['condition_id'][:16]} result_yes={r['result_yes']} pnl=${r.get('pnl', 0):.2f}")
    conn.close()

if out_lines:
    print("\n".join(out_lines))
# empty stdout = silent
