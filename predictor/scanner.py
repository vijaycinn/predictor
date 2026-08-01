"""Scan orchestration: one cycle of discover -> ingest -> feature -> signal -> risk -> execute."""
from __future__ import annotations

import json
import time

from . import db, executor as executor_mod, features as features_mod, ingest, learn, risk as risk_mod, signals as sig_mod


def get_venue(cfg: dict):
    """Venue ingest module: ingest (Polymarket) or kalshi, same function surface."""
    if cfg.get("venue") == "kalshi":
        from . import kalshi
        return kalshi
    return ingest


def run_scan(conn, cfg: dict, llm_overrides: dict | None = None, verbose: bool = False) -> dict:
    """llm_overrides: {condition_id: prob_yes} from optional LLM review pass."""
    llm_overrides = llm_overrides or {}
    scan_cfg = cfg.get("scan", {})
    min_recent = scan_cfg.get("min_recent_trades", 5)

    # 1. resolution pass first (settle anything already closed)
    resolved = learn.check_resolutions(conn)

    # 2. discover candidate markets
    ing = get_venue(cfg)
    markets = ing.discover_markets(cfg)
    if verbose:
        print(f"[scan] venue={cfg.get('venue', 'polymarket')} discovered {len(markets)} candidate markets")

    exec_mod_inst = executor_mod.make_executor(conn, cfg)
    signals = []
    top = []
    shortlist = []
    skipped = []

    for market in markets:
        cid = market["condition_id"]
        db.upsert_market(conn, market)
        token_yes = market["clob_token_ids"][0] if market.get("clob_token_ids") else ""

        try:
            book = ing.fetch_orderbook(token_yes)
            history = ing.fetch_price_history(cid, interval="1w", fidelity=168)
            trades = ing.fetch_recent_trades(cid, limit=25)
            oi = ing.fetch_open_interest(cid)
        except Exception as e:
            skipped.append((cid, str(e)))
            continue

        if len(trades) < min_recent:
            skipped.append((cid, f"only {len(trades)} recent trades"))
            continue

        feats = features_mod.build_features(market, book, history, trades, oi, cfg)
        db.insert_features(conn, cid, feats)
        db.insert_snapshot(conn, cid, feats)

        llm_p = llm_overrides.get(cid)
        sig = sig_mod.build_signal(market, feats, llm_p, cfg)
        sig["signal_id"] = db.insert_signal(conn, sig)
        signals.append(sig)

        # shortlist for LLM review: edge candidates first, top-N liquid markets to fill
        entry = {
            "condition_id": cid,
            "question": market["question"],
            "category": market["category"],
            "mid": feats.get("mid"),
            "spread": feats.get("spread"),
            "depth": feats.get("depth_total"),
            "liquidity": market.get("liquidity"),
            "imbalance": feats.get("imbalance"),
            "momentum": feats.get("momentum"),
            "flow": feats.get("trade_flow"),
            "hours_to_expiry": feats.get("hours_to_expiry"),
            "prob_yes_auto": sig["prob_yes"],
            "edge": sig["edge"],
            "ev_net": sig["ev_net"],
            "action": sig["action"],
            "end_date": market.get("end_date"),
        }
        spread = feats.get("spread")
        depth = feats.get("depth_total") or 0
        if feats.get("mid") is not None and spread is not None and spread <= 0.10 and depth >= 100:
            shortlist.append(entry)

        if sig["action"] != "BUY":
            skipped.append((cid, f"action={sig['action']} edge={sig['edge']:.3f}"))
            continue

        # mechanical filters
        ok, reason = risk_mod.check_filters(feats, sig, cfg)
        if not ok:
            db.block_trade(conn, cid, sig.get("side") or "?", reason, json.dumps(sig.get("metrics_snapshot", {}), default=str)[:500])
            skipped.append((cid, reason))
            continue

        # sizing
        frac = risk_mod.kelly_size(sig, cfg)
        if frac <= 0:
            db.block_trade(conn, cid, sig.get("side") or "?", "kelly size 0", "")
            skipped.append((cid, "kelly size 0"))
            continue

        capital = cfg.get("risk", {}).get("capital_usd", 1000)
        size_contracts = max(1.0, int((frac * capital) / max(sig["ev_calc"]["price_side"], 0.01)))

        # risk limits
        ok2, reason2 = risk_mod.check_risk_limits(conn, sig, frac, cfg)
        if not ok2:
            db.block_trade(conn, cid, sig.get("side") or "?", reason2, "")
            skipped.append((cid, reason2))
            continue

        limit = risk_mod.limit_price(sig, feats, cfg)
        trade = exec_mod_inst.execute(sig, size_contracts, limit, feats)
        sig["trade"] = trade
        top.append({
            "question": market["question"],
            "category": market["category"],
            "side": sig["side"],
            "prob_yes": sig["prob_yes"],
            "confidence": sig["confidence"],
            "confidence_tier": sig["confidence_tier"],
            "ev_net": sig["ev_net"],
            "edge": sig["edge"],
            "market_price": sig["market_price"],
            "size": trade["size"],
            "fill": trade["fill_price"],
            "status": trade["status"],
            "reasoning": sig["reasoning"],
        })
        if verbose:
            print(f"[scan] TRADE {market['question'][:60]} -> {sig['side']} {size_contracts} @ {limit} ({trade['status']})")

    top.sort(key=lambda t: t["ev_net"], reverse=True)

    # shortlist assembly: edge candidates first, then top-N liquid markets to fill
    shortlist_edge = cfg.get("prob", {}).get("shortlist_edge", 0.008)
    shortlist_max = cfg.get("prob", {}).get("shortlist_max", 10)
    edge_cands = sorted(
        (e for e in shortlist if abs(e["edge"]) >= shortlist_edge),
        key=lambda e: abs(e["edge"]), reverse=True,
    )
    liquid_cands = sorted(
        (e for e in shortlist if e not in edge_cands),
        key=lambda e: (e.get("depth") or 0), reverse=True,
    )
    shortlist = (edge_cands + liquid_cands)[:shortlist_max]

    return {
        "ts": time.time(),
        "markets_evaluated": len(markets),
        "signals_generated": len(signals),
        "trades_proposed": len(top),
        "trades_filled": sum(1 for t in top if t["status"] in ("OPEN", "PARTIAL")),
        "resolved": resolved,
        "top": top,
        "shortlist": shortlist,
        "skipped": skipped[:50],
    }
