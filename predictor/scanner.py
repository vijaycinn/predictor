"""Scan orchestration: one cycle of discover -> ingest -> feature -> signal -> risk -> (propose | execute)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import db, executor as executor_mod, features as features_mod, ingest, learn, risk as risk_mod, signals as sig_mod


def get_venue(cfg: dict):
    """Venue ingest module: ingest (Polymarket) or kalshi, same function surface."""
    if cfg.get("venue") == "kalshi":
        from . import kalshi
        return kalshi
    return ingest


def market_from_db(row) -> dict:
    """Reconstruct a market dict from a markets table row."""
    def _jl(s, default):
        try:
            return json.loads(s or default)
        except json.JSONDecodeError:
            return json.loads(default)
    return {
        "condition_id": row["condition_id"],
        "question": row["question"],
        "slug": row["slug"],
        "category": row["category"],
        "event_id": row["event_id"],
        "end_date": row["end_date"],
        "created_at": row["created_at"],
        "volume": row["volume"],
        "liquidity": row["liquidity"],
        "open_interest": row["open_interest"],
        "outcomes": _jl(row["outcomes"], "[]"),
        "outcome_prices": _jl(row["outcome_prices"], "[]"),
        "clob_token_ids": _jl(row["clob_token_ids"], '["",""]'),
        "active": bool(row["active"]),
        "closed": bool(row["closed"]),
        "fees_enabled": False,
        "taker_base_fee": 0.0,
        "maker_base_fee": 0.0,
    }


def fetch_market_by_id(cfg: dict, cid: str) -> dict | None:
    """Fresh venue market record; venue modules implement per-id fetch."""
    ing = get_venue(cfg)
    return ing.fetch_market_by_id(cid)


def evaluate_market(conn, cfg: dict, ing, market: dict, llm_p: float | None = None) -> tuple[dict, dict] | None:
    """Ingest -> features -> signal for one market. Returns (sig, feats) or None."""
    cid = market["condition_id"]
    db.upsert_market(conn, market)
    token_yes = market["clob_token_ids"][0] if market.get("clob_token_ids") else ""
    try:
        book = ing.fetch_orderbook(token_yes)
        history = ing.fetch_price_history(cid, interval="1w", fidelity=168)
        trades = ing.fetch_recent_trades(cid, limit=25)
        oi = ing.fetch_open_interest(cid)
    except Exception:
        return None
    min_recent = cfg.get("scan", {}).get("min_recent_trades", 5)
    if len(trades) < min_recent:
        return None
    feats = features_mod.build_features(market, book, history, trades, oi, cfg)
    db.insert_features(conn, cid, feats)
    db.insert_snapshot(conn, cid, feats)
    sig = sig_mod.build_signal(market, feats, llm_p, cfg)
    sig["signal_id"] = db.insert_signal(conn, sig)
    return sig, feats


def _size_trade(sig: dict, cfg: dict) -> tuple[float, float]:
    """(size_dollars, size_contracts). Paper: full Kelly on virtual capital —
    no caps, thesis validation. Live: hard-capped at max_trade_usd."""
    frac = risk_mod.kelly_size(sig, cfg)
    if frac <= 0:
        return 0.0, 0.0
    capital = cfg.get("risk", {}).get("capital_usd", 1000)
    size_dollars = frac * capital
    if cfg.get("mode") == "live":
        max_trade = cfg.get("risk", {}).get("max_trade_usd", 2.0)
        size_dollars = min(size_dollars, max_trade)
    price_side = max(sig["ev_calc"]["price_side"], 0.01)
    size_contracts = max(1.0, int(size_dollars / price_side))
    return size_dollars, size_contracts


def check_position_cap(conn, cfg: dict) -> tuple[bool, str]:
    """Max concurrent open positions (both modes). VJ-controlled:
    runtime override (data/runtime.json max_open_positions) wins, else config.
    Set via: python3 cli.py max-open <N>"""
    cap = cfg.get("risk", {}).get("max_open_positions", 5)
    rt = runtime_settings(cfg)
    if rt.get("max_open_positions") is not None:
        cap = rt["max_open_positions"]
    open_count = len(db.open_positions(conn))
    if open_count >= cap:
        return False, f"max_open_positions reached ({open_count}/{cap})"
    return True, ""


def runtime_settings(cfg: dict) -> dict:
    """Persistent runtime overrides from data/runtime.json (survives restarts,
    gitignored — machine-local). VJ explicit control via cli.py max-open."""
    path = _runtime_path(cfg)
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def set_runtime_setting(cfg: dict, key: str, value) -> dict:
    path = _runtime_path(cfg)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = runtime_settings(cfg)
    data[key] = value
    Path(path).write_text(json.dumps(data, indent=2))
    return data


def _runtime_path(cfg: dict) -> Path:
    # next to config: <repo>/data/runtime.json (data/ is gitignored)
    return Path(cfg.get("_config_path", ".")).parent / "data" / "runtime.json"


def run_scan(conn, cfg: dict, llm_overrides: dict | None = None, verbose: bool = False) -> dict:
    """llm_overrides: {condition_id: prob_yes} from optional LLM review pass."""
    risk_mod.assert_no_margin(cfg)  # NO MARGIN TRADING EVER (all modes)
    approval_cfg = cfg.get("approval", {})
    is_live = cfg.get("mode") == "live"
    # approval gate: LIVE ONLY. Paper executes autonomously (thesis validation).
    approval_required = is_live and approval_cfg.get("required", True)
    llm_overrides = llm_overrides or {}

    # 1. resolution pass first (settle anything already closed)
    resolved = learn.check_resolutions(conn)

    # 2. order lifecycle: fill/cancel resting orders (paper + live)
    order_events = executor_mod.reconcile_orders(conn, cfg)

    # 3. expire stale proposals
    expired = db.expire_stale_proposals(conn, approval_cfg.get("ttl_hours", 2.0))

    # 3. discover candidate markets
    ing = get_venue(cfg)
    markets = ing.discover_markets(cfg)
    if verbose:
        print(f"[scan] venue={cfg.get('venue', 'polymarket')} discovered {len(markets)} candidate markets")

    # VIX REGIME GATE (VJ cheat code, rule 20, 2026-08-09): fear gauge filter.
    # BUY zone (VIX>30): panic -> keep cheap recovery/risk-on candidates.
    # TRIM zone (VIX<15): complacency -> suppress new aggressive longs.
    # NEUTRAL: normal. Never a standalone signal — filter only.
    vix_regime = {"vix": None, "zone": "NEUTRAL"}
    try:
        from scripts.vix_regime import get_vix, regime as vix_regime_of
        _vix = get_vix()
        if _vix is not None:
            vix_regime = {"vix": _vix, "zone": vix_regime_of(_vix)}
    except Exception as e:
        if verbose:
            print(f"[scan] vix gate unavailable: {str(e)[:60]}")
    trim_zone = vix_regime["zone"] == "TRIM"

    exec_mod_inst = executor_mod.make_executor(conn, cfg)
    signals = []
    top = []
    shortlist = []
    skipped = []

    for market in markets:
        cid = market["condition_id"]
        llm_p = llm_overrides.get(cid)
        ev = evaluate_market(conn, cfg, ing, market, llm_p)
        if ev is None:
            skipped.append((cid, "ingest failed / insufficient data"))
            continue
        sig, feats = ev
        signals.append(sig)

        # shortlist for LLM review: edge candidates first, top-N liquid markets to fill
        spread = feats.get("spread")
        depth = feats.get("depth_total") or 0
        if feats.get("mid") is not None and spread is not None and spread <= 0.10 and depth >= 100:
            shortlist.append({
                "condition_id": cid,
                "question": market["question"],
                "category": market["category"],
                "mid": feats.get("mid"),
                "spread": spread,
                "depth": depth,
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
            })

        if sig["action"] != "BUY":
            skipped.append((cid, f"action={sig['action']} edge={sig['edge']:.3f}"))
            continue

        # mechanical filters
        ok, reason = risk_mod.check_filters(feats, sig, cfg)
        if not ok:
            db.block_trade(conn, cid, sig.get("side") or "?", reason, json.dumps(sig.get("metrics_snapshot", {}), default=str)[:500])
            skipped.append((cid, reason))
            continue

        size_dollars, size_contracts = _size_trade(sig, cfg)
        if size_dollars <= 0:
            db.block_trade(conn, cid, sig.get("side") or "?", "kelly size 0", "")
            skipped.append((cid, "kelly size 0"))
            continue

        # risk limits
        ok2, reason2 = risk_mod.check_risk_limits(conn, sig, size_dollars, cfg)
        if not ok2:
            db.block_trade(conn, cid, sig.get("side") or "?", reason2, "")
            skipped.append((cid, reason2))
            continue

        # position cap (both modes)
        ok3, reason3 = check_position_cap(conn, cfg)
        if not ok3:
            db.block_trade(conn, cid, sig.get("side") or "?", reason3, "")
            skipped.append((cid, reason3))
            continue

        limit = risk_mod.limit_price(sig, feats, cfg)

        if approval_required:
            # HARD GATE: no execution without explicit user approval
            pid = db.insert_proposal(conn, {
                "condition_id": cid,
                "question": market["question"],
                "side": sig["side"],
                "size": size_contracts,
                "limit_price": limit,
                "price_side": sig["ev_calc"]["price_side"],
                "ev_net": sig["ev_net"],
                "confidence": sig["confidence"],
                "prob_yes": sig["prob_yes"],
                "note": sig["reasoning"],
                "llm_override": llm_p,
            })
            top.append({
                "proposal_id": pid,
                "question": market["question"],
                "category": market["category"],
                "side": sig["side"],
                "prob_yes": sig["prob_yes"],
                "confidence": sig["confidence"],
                "confidence_tier": sig["confidence_tier"],
                "ev_net": sig["ev_net"],
                "edge": sig["edge"],
                "market_price": sig["market_price"],
                "size": size_contracts,
                "limit": limit,
                "notional_usd": round(sig["ev_calc"]["price_side"] * size_contracts, 2),
                "status": "PENDING_APPROVAL",
                "reasoning": sig["reasoning"],
            })
            if verbose:
                print(f"[scan] PROPOSE #{pid} {market['question'][:50]} -> {sig['side']} {size_contracts} @ {limit} (${size_dollars:.2f})")
        else:
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

    top.sort(key=lambda t: t.get("ev_net", 0), reverse=True)

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

    # SUGGESTION SUPPRESSION (VJ 2026-08-02, post-loss retrospective): never
    # SUGGEST a bet whose outcome prob < min_win_prob. If we shouldn't take it,
    # we shouldn't offer it either — lottery tickets are not options. mid < 0.50
    # means the market itself prices <50% (no edge, no research case).
    min_win = cfg.get("execution", {}).get("min_win_prob", 0.50)
    shortlist = [e for e in shortlist if (e.get("mid") or 0) >= min_win]
    top = [t for t in top if t.get("market_price", t.get("prob_yes", 0)) >= min_win]

    # VIX REGIME GATE on shortlist (rule 20, 2026-08-09): in TRIM zone (VIX<15,
    # complacency) suppress NEW long entries — trim winners, don't chase
    # euphoria. Proposals already PENDING_APPROVAL stay (user decision); only
    # new signals/auto shortlist items are cut. BUY zone (VIX>30) keeps all.
    vix_filtered = 0
    if trim_zone:
        _before = len(shortlist)
        shortlist = [e for e in shortlist if e.get("side") != "YES"]
        vix_filtered = _before - len(shortlist)
        if vix_filtered:
            skipped.append({"reason": f"vix_trim_zone ({vix_regime['vix']:.1f})", "count": vix_filtered})

    return {
        "ts": time.time(),
        "venue": cfg.get("venue", "polymarket"),
        "vix_regime": vix_regime,
        "markets_evaluated": len(markets),
        "signals_generated": len(signals),
        "proposals": len([t for t in top if t["status"] == "PENDING_APPROVAL"]),
        "trades_executed": len([t for t in top if t["status"] not in ("PENDING_APPROVAL",)]),
        "trades_filled": sum(1 for t in top if t["status"] in ("OPEN", "PARTIAL")),
        "order_events": order_events,
        "stale_expired": expired,
        "resolved": resolved,
        "top": top,
        "shortlist": shortlist,
        "skipped": skipped[:50],
        "vix_filtered": vix_filtered,
    }


def execute_proposal(conn, cfg: dict, pid: int, verbose: bool = False) -> dict:
    """Execute an approved proposal after fresh EV/liquidity re-check.

    Hard gates re-applied at execution time: margin off, size <= max_trade_usd,
    filters pass, EV_net >= ev_min_net. Fails closed: any check failure rejects
    the proposal with a note instead of trading blind.
    """
    risk_mod.assert_no_margin(cfg)
    if cfg.get("mode") != "live":
        return {"ok": False, "error": "approval flow is LIVE only; paper mode executes autonomously"}
    approval_cfg = cfg.get("approval", {})
    recheck = approval_cfg.get("recheck_on_approve", True)

    prop = db.get_proposal(conn, pid)
    if prop is None:
        return {"ok": False, "error": f"proposal #{pid} not found"}
    if prop["status"] != "PENDING":
        return {"ok": False, "error": f"proposal #{pid} status={prop['status']} (not PENDING)"}

    ing = get_venue(cfg)
    market = None
    try:
        market = ing.fetch_market_by_id(prop["condition_id"])
    except Exception:
        market = None
    if market is None:
        row = conn.execute("SELECT * FROM markets WHERE condition_id=?", (prop["condition_id"],)).fetchone()
        if row:
            market = market_from_db(row)
    if market is None:
        db.set_proposal_status(conn, pid, "REJECTED", note="market lookup failed at execution")
        return {"ok": False, "error": "market lookup failed"}
    if market.get("condition_id") != prop["condition_id"]:
        db.set_proposal_status(conn, pid, "REJECTED", note=f"market mismatch: got {market.get('condition_id')}")
        return {"ok": False, "error": "market mismatch at execution"}

    ev = evaluate_market(conn, cfg, ing, market, llm_p=prop.get("llm_override"))
    if ev is None:
        db.set_proposal_status(conn, pid, "REJECTED", note="re-check: ingest failed / insufficient data")
        return {"ok": False, "error": "re-check ingest failed"}
    sig, feats = ev

    if recheck:
        problems = []
        if sig["action"] != "BUY":
            problems.append(f"action now {sig['action']} (edge {sig['edge']:.3f})")
        ok, reason = risk_mod.check_filters(feats, sig, cfg)
        if not ok:
            problems.append(reason)
        ev_min = cfg.get("execution", {}).get("ev_min_net", 0.02)
        if sig["ev_net"] is not None and sig["ev_net"] < ev_min:
            problems.append(f"EV_net {sig['ev_net']:.4f} < min {ev_min}")
        if problems:
            db.set_proposal_status(conn, pid, "REJECTED", note="; ".join(problems))
            return {"ok": False, "error": "re-check rejected: " + "; ".join(problems)}

    size_dollars, size_contracts = _size_trade(sig, cfg)
    max_trade = cfg.get("risk", {}).get("max_trade_usd", 2.0)
    if size_dollars <= 0 or size_dollars > max_trade:
        db.set_proposal_status(conn, pid, "REJECTED", note=f"size ${size_dollars:.2f} outside cap")
        return {"ok": False, "error": f"size ${size_dollars:.2f} outside cap"}

    ok2, reason2 = risk_mod.check_risk_limits(conn, sig, size_dollars, cfg)
    if not ok2:
        db.set_proposal_status(conn, pid, "REJECTED", note=reason2)
        return {"ok": False, "error": reason2}

    limit = risk_mod.limit_price(sig, feats, cfg)
    exec_mod_inst = executor_mod.make_executor(conn, cfg)
    trade = exec_mod_inst.execute(sig, size_contracts, limit, feats)
    db.set_proposal_status(conn, pid, "APPROVED", note="executed after approval", trade_id=trade.get("id"))
    if verbose:
        print(f"[approve] #{pid} {market['question'][:50]} -> {sig['side']} {size_contracts} @ {limit} ({trade['status']})")
    return {
        "ok": True,
        "proposal_id": pid,
        "trade_id": trade.get("id"),
        "status": trade["status"],
        "side": sig["side"],
        "size": trade["size"],
        "limit": limit,
        "fill": trade["fill_price"],
        "notional_usd": round(sig["ev_calc"]["price_side"] * size_contracts, 2),
        "question": market["question"],
    }
