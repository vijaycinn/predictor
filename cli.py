#!/usr/bin/env python3
"""predictor CLI: scan | status | calibrate | resolve"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from predictor import db, learn
from predictor.config import load_config

DEFAULT_DB = str(Path(__file__).parent / "data" / "predictor.db")
DEFAULT_CFG = str(Path(__file__).parent / "config.yaml")


def cmd_scan(args):
    cfg = load_config(args.config)
    if args.venue:
        cfg["venue"] = args.venue
    conn = db.connect(args.db)
    llm_overrides = {}
    if args.llm_overrides:
        llm_overrides = json.loads(Path(args.llm_overrides).read_text())
    from predictor.scanner import run_scan
    result = run_scan(conn, cfg, llm_overrides=llm_overrides, verbose=args.verbose)
    if cfg["venue"] == "kalshi":
        from predictor import kalshi
        print("kalshi auth:", kalshi.auth_ready(), file=sys.stderr)
    if args.shortlist:
        Path(args.shortlist).write_text(json.dumps(result["shortlist"], indent=2, default=str))
        print(f"shortlist written: {args.shortlist} ({len(result['shortlist'])} candidates)")
    else:
        print(json.dumps(result, indent=2, default=str))


def cmd_status(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    from predictor.scanner import runtime_settings
    positions = db.open_positions(conn)
    rt = runtime_settings(cfg)
    cap = rt.get("max_open_positions") or cfg.get("risk", {}).get("max_open_positions", 5)
    print(f"Open positions: {len(positions)} / cap {cap}" + (" (runtime override)" if rt.get("max_open_positions") is not None else ""))
    total_cost = 0.0
    for p in positions:
        px = p["fill_price"] or p["limit_price"] or 0
        total_cost += px * p["size"]
        print(f"  {p['condition_id'][:10]} {p['side']:>3} x{p['size']:.0f} @ {px:.3f} | {p['question'][:60]}")
    print(f"Capital deployed: ${total_cost:.2f}")
    perf = learn.performance_summary(conn)
    print("Performance:", json.dumps(perf, indent=2))


def cmd_max_open(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    from predictor.scanner import runtime_settings, set_runtime_setting
    if args.value is None:
        rt = runtime_settings(cfg)
        eff = rt.get("max_open_positions") or cfg.get("risk", {}).get("max_open_positions", 5)
        cur = len(db.open_positions(conn))
        print(f"max_open_positions: {eff} (open now: {cur})")
        if rt.get("max_open_positions") is not None:
            print(f"  runtime override active: {rt['max_open_positions']} (data/runtime.json)")
        else:
            print(f"  config default: {cfg.get('risk', {}).get('max_open_positions', 5)} (data/runtime.json not set)")
        return
    v = int(args.value)
    if v < 1:
        print("max-open must be >= 1")
        return
    rt = set_runtime_setting(cfg, "max_open_positions", v)
    cur = len(db.open_positions(conn))
    print(f"max_open_positions set: {rt['max_open_positions']} (open now: {cur})")
    if cur >= v:
        print(f"  WARNING: {cur} open >= cap {v} — no new entries until positions close.")


def cmd_proposals(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    db.expire_stale_proposals(conn, cfg.get("approval", {}).get("ttl_hours", 2.0))
    pending = db.pending_proposals(conn)
    if not pending:
        print("No pending proposals.")
        return
    # VJ eval format (2026-08-05): every proposal carries a decision marker —
    # 👍 = approve/buy, 👎 = reject/skip. One line each, decision first.
    print(f"{len(pending)} pending proposal(s). Reply: 👍 <id> approve | 👎 <id> reject")
    for p in pending:
        ev_c = p["ev_net"] * 100
        print(
            f"#{p['id']:>3} 👍 {p['side']:>3} x{p['size']:.0f} @ {p['limit_price']:.3f} "
            f"(${p['price_side'] * p['size']:.2f}) ev={ev_c:+.1f}c conf={p['confidence']:.2f} | {p['question'][:60]}"
        )
    print("👍 = APPROVE (place order) | 👎 = REJECT (skip)")


def cmd_approve(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    if args.venue:
        cfg["venue"] = args.venue
    from predictor.scanner import execute_proposal
    for pid in args.ids:
        res = execute_proposal(conn, cfg, pid, verbose=False)
        print(json.dumps(res, indent=2, default=str))


def cmd_reject(args):
    conn = db.connect(args.db)
    for pid in args.ids:
        p = db.get_proposal(conn, pid)
        if p is None:
            print(f"#{pid}: not found")
        elif p["status"] != "PENDING":
            print(f"#{pid}: status={p['status']} (not PENDING)")
        else:
            db.set_proposal_status(conn, pid, "REJECTED", note="rejected by user")
            print(f"#{pid}: rejected")


def cmd_orders(args):
    conn = db.connect(args.db)
    rows = conn.execute(
        """SELECT t.id, t.condition_id, m.question, t.side, t.status, t.requested_size,
                  t.filled_size, t.limit_price, t.fill_price, t.exchange_order_id,
                  t.order_status, t.ttl_expires_at
           FROM trades t LEFT JOIN markets m ON m.condition_id=t.condition_id
           WHERE t.status IN ('RESTING','OPEN','PARTIAL') ORDER BY t.id"""
    ).fetchall()
    if not rows:
        print("No open/resting orders.")
        return
    for r in rows:
        print(
            f"#{r['id']:>3} {r['status']:8} {r['side']:>3} req={r['requested_size'] or 0:.0f} "
            f"fill={r['filled_size'] or 0:.0f} @ {r['limit_price'] or r['fill_price']} "
            f"ord={r['order_status'] or '-'} | {str(r['question'])[:42]}"
        )


def _infer_venue(condition_id: str) -> str:
    """Kalshi tickers look like KX...; Polymarket condition ids are 0x hex."""
    return "polymarket" if str(condition_id).startswith("0x") else "kalshi"


def cmd_close(args):
    """Manual position exit. Paper: closes at current book mid (sell side).
    Live kalshi: places reduce_only sell order. NO stop-loss (by design)."""
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    if args.venue:
        cfg["venue"] = args.venue
    from predictor.scanner import get_venue
    for tid in args.ids:
        t = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
        if not t:
            print(f"#{tid}: not found")
            continue
        cfg["venue"] = args.venue or _infer_venue(t["condition_id"])
        ing = get_venue(cfg)
        if t["status"] != "OPEN":
            print(f"#{tid}: status={t['status']} (only OPEN positions can close)")
            continue
        try:
            book = ing.fetch_orderbook(t["condition_id"])
        except Exception as e:
            print(f"#{tid}: book fetch failed: {e}")
            continue
        side = t["side"]
        if side == "YES":
            exit_px = book.get("best_bid")
        else:
            exit_px = (1.0 - book.get("best_ask")) if book.get("best_ask") is not None else None
        if exit_px is None:
            print(f"#{tid}: no exit price in book")
            continue
        entry = t["fill_price"] or t["limit_price"]
        if entry is None:
            print(f"#{tid}: no entry price on record")
            continue
        size = t["size"] or 0
        pnl = (exit_px - entry) * size
        if cfg.get("mode") == "live":
            from predictor.executor import make_executor
            ex = make_executor(conn, cfg)
            ks = getattr(ex, "kalshi", None)
            if ks is None:
                print(f"#{tid}: live close needs kalshi executor")
                continue
            resp = ks.place_order(t["condition_id"], side, size, exit_px, reduce_only=True)
            print(f"#{tid}: live sell order placed (reduce_only) at {exit_px}: {resp}")
        db.update_trade(conn, tid, {"status": "CLOSED", "fill_price": exit_px, "pnl": pnl,
                                    "order_status": "closed_manual",
                                    "exit_reason": args.reason})
        print(f"#{tid}: closed {side} x{size:.0f} entry={entry:.4f} exit={exit_px:.4f} pnl=${pnl:.2f} reason={args.reason}")


def cmd_cancel(args):
    """Cancel a resting order (live: also cancels on exchange)."""
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    if args.venue:
        cfg["venue"] = args.venue
    for tid in args.ids:
        t = conn.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
        if not t:
            print(f"#{tid}: not found")
            continue
        cfg["venue"] = args.venue or _infer_venue(t["condition_id"])
        if t["status"] != "RESTING":
            print(f"#{tid}: status={t['status']} (only RESTING orders can cancel)")
            continue
        if cfg.get("mode") == "live" and t["exchange_order_id"]:
            from predictor.executor import make_executor
            try:
                ex = make_executor(conn, cfg)
                cancel_fn = getattr(ex, "cancel", None)
                if cancel_fn is None:
                    raise RuntimeError("live cancel not available")
                cancel_fn(tid)
                print(f"#{tid}: cancelled on exchange + locally")
                continue
            except Exception as e:
                print(f"#{tid}: exchange cancel failed: {e}")
        db.update_trade(conn, tid, {"status": "CANCELED", "order_status": "canceled_manual"})
        print(f"#{tid}: cancelled")


def cmd_sumarb(args):
    """Intra-market sum-to-1 rebalancing arb scanner (report-only)."""
    from predictor import sumarb
    res = sumarb.scan(min_edge_cents=args.min_edge, limit=args.limit)
    print(f"markets fetched: {res['markets_fetched']} | events seen: {res['events_seen']} | "
          f"partition candidates: {res['partition_candidates']} | opportunities: {len(res['opportunities'])}")
    if not res["opportunities"]:
        print("\nNo sum-to-1 arb opportunities above min edge after fees/slippage.")
        return
    for o in res["opportunities"]:
        print()
        print(sumarb.format_opportunity(o))
    if args.json:
        print("\n" + json.dumps(res["opportunities"], indent=2, default=str))


def cmd_comb(args):
    """Combinatorial arb: auto-discovered ladder monotonicity + winner/margin."""
    from predictor import combinatorial
    print("[combinatorial] ladder monotonicity (auto-discovered series)")
    print("=" * 72)
    series = combinatorial.discover_ladder_series()
    found = 0
    for s in series:
        viols = combinatorial.monotonicity_violations(s, min_volume=args.min_vol)
        for v in viols:
            found += 1
            print(f"  {v['series']}: P(>{v['lower_strike']:.0f}) ask {v['lower_yes_ask']:.3f} "
                  f"< P(>{v['upper_strike']:.0f}) ask {v['upper_yes_ask']:.3f} | net {v['net_edge']*100:+.1f}c "
                  f"{'TRADE' if v['net_edge'] > 0 else 'no-edge'}")
            print(f"      {v['lower_ticker']} | {v['upper_ticker']}")
    if found == 0:
        print("  no monotonicity violations found")
    print("=" * 72)
    print("[combinatorial] winner vs margin dependency")
    print("=" * 72)
    wm = combinatorial.scan_winner_margin(min_edge_cents=args.min_edge)
    print(f"winner markets: {wm['winner_markets']} | margin markets: {wm['margin_markets']} | violations: {len(wm['violations'])}")
    for v in wm["violations"]:
        print(f"  {v['subject'][:30]:32} winner ask {v['winner_yes_ask']:.3f} < margin "
              f"(>{v['margin_threshold']}) ask {v['margin_yes_ask']:.3f} | net {v['net_edge']*100:+.1f}c")
        print(f"      {v['winner_ticker']} | {v['margin_ticker']}")
    if args.json:
        print("\n" + json.dumps({"monotonicity": [
            v for s in series for v in combinatorial.monotonicity_violations(s, min_volume=args.min_vol)],
            "winner_margin": wm["violations"]}, indent=2, default=str))


def cmd_arb(args):
    """Predexon-driven arb check: Kalshi candidates vs Polymarket equivalents."""
    from predictor import arb, predexon
    if args.health:
        print("predexon health:", predexon.health())
        return
    if args.pmxt:
        from predictor import pmxt
        res = pmxt.ranked_opportunities(min_net_edge=0.0, limit=args.limit)
        print(f"PMXT Router arb feed | total: {res['total_arbs']} | kalshi legs: {res['kalshi_legs']} | net-edge list below")
        for o in res["opportunities"][:args.limit]:
            k = f" K={o.get('kalshi_ticker')}" if o.get("kalshi_ticker") else ""
            flag = "EXECUTABLE" if o.get("kalshi_ticker") else "discovery-only"
            print(f"  {o['net_edge']*100:6.2f}% {o['buy_venue']:10}->{o['sell_venue']:10} {o['buy_price']:.4f}/{o['sell_price']:.4f} | {o['title_a'][:34]} [{flag}]{k}")
            print(f"        [{o['validation']}]")
        return
    cfg = load_config(args.config)
    if args.min_volume:
        cfg["scan"] = {**cfg.get("scan", {}), "min_volume_usd": args.min_volume}
    if args.check:
        res = arb.arb_check(cfg, min_volume=args.min_volume, limit=args.limit)
        print(f"Kalshi scanned: {res['kalshi_scanned']} | matched: {res['with_match']} (weak dropped: {res.get('weak_dropped', 0)}) | positive-net: {len(res['positive'])}")
        for o in res["positive"]:
            print()
            print(arb.format_opportunity(o))
        if not res["positive"]:
            print("\nNo positive-net arb opportunities after fees/slippage.")
            # fall back to top mispriced Kalshi markets (non-arb)
            print("\n--- Top mispriced Kalshi candidates (non-arb, labeled) ---")
            for k in predexon.list_kalshi_markets(status="open", min_volume=args.min_volume, limit=8):
                kp = arb.kalshi_prices(k)
                if kp:
                    mid = ((kp["yes_bid"] or 0) + (kp["yes_ask"] or 0)) / 2
                    print(f"  {k['ticker'][:38]:40} YES {mid:.3f} | {k.get('title','')[:50]}")
    else:
        res = arb.best_kalshi_trades(cfg, min_volume=args.min_volume, limit=args.limit)
        print(f"Kalshi scanned: {res['kalshi_scanned']} | matched: {res['with_match']} | opportunities: {len(res['opportunities'])}")
        for o in res["opportunities"][:5]:
            print()
            print(arb.format_opportunity(o))


def cmd_calibrate(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    report = learn.calibration_report(conn, cfg)
    print(json.dumps(report, indent=2, default=str))


def cmd_resolve(args):
    conn = db.connect(args.db)
    resolved = learn.check_resolutions(conn)
    print(json.dumps(resolved, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(prog="predictor", description="Prediction market trading agent")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--config", default=DEFAULT_CFG)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="run one full scan cycle")
    p_scan.add_argument("--llm-overrides", default=None, help="path to JSON {condition_id: prob_yes}")
    p_scan.add_argument("--shortlist", default=None, help="write LLM review shortlist JSON to this path")
    p_scan.add_argument("--venue", default=None, choices=["polymarket", "kalshi", "polymarket_us"], help="override venue from config")
    p_scan.add_argument("--verbose", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_status = sub.add_parser("status", help="positions + performance")
    p_status.set_defaults(func=cmd_status)

    p_mo = sub.add_parser("max-open", help="show/set max open positions (VJ explicit control; persists in data/runtime.json)")
    p_mo.add_argument("value", nargs="?", type=int, help="new cap (omit to show current)")
    p_mo.set_defaults(func=cmd_max_open)

    p_prop = sub.add_parser("proposals", help="list pending trade proposals awaiting approval")
    p_prop.set_defaults(func=cmd_proposals)

    p_ap = sub.add_parser("approve", help="approve + execute proposals (re-verifies EV first)")
    p_ap.add_argument("ids", nargs="+", type=int, help="proposal IDs")
    p_ap.add_argument("--venue", default=None, choices=["polymarket", "kalshi", "polymarket_us"])
    p_ap.set_defaults(func=cmd_approve)

    p_rj = sub.add_parser("reject", help="reject proposals")
    p_rj.add_argument("ids", nargs="+", type=int, help="proposal IDs")
    p_rj.set_defaults(func=cmd_reject)

    p_ord = sub.add_parser("orders", help="list open/resting orders (lifecycle view)")
    p_ord.set_defaults(func=cmd_orders)

    p_cl = sub.add_parser("close", help="close an open position (paper: at book; live: reduce_only sell)")
    p_cl.add_argument("ids", nargs="+", type=int, help="trade IDs")
    p_cl.add_argument("--venue", default=None, choices=["polymarket", "kalshi", "polymarket_us"])
    p_cl.add_argument("--reason", default="manual", help="exit rationale (rule 6: 91c+ TP or VJ direction; logged to DB exit_reason)")
    p_cl.set_defaults(func=cmd_close)

    p_cx = sub.add_parser("cancel", help="cancel a resting order (live: also on exchange)")
    p_cx.add_argument("ids", nargs="+", type=int, help="trade IDs")
    p_cx.add_argument("--venue", default=None, choices=["polymarket", "kalshi", "polymarket_us"])
    p_cx.set_defaults(func=cmd_cancel)

    p_arb = sub.add_parser("arb", help="arb check: Kalshi vs Polymarket (Predexon) or PMXT Router feed")
    p_arb.add_argument("--check", action="store_true", help="positive-net only + mispriced fallback")
    p_arb.add_argument("--health", action="store_true", help="Predexon API health check")
    p_arb.add_argument("--pmxt", action="store_true", help="use PMXT Router arb feed (hosted, cross-venue)")
    p_arb.add_argument("--min-volume", type=int, default=5000, help="min Kalshi dollar volume")
    p_arb.add_argument("--limit", type=int, default=30, help="max opportunities")
    p_arb.set_defaults(func=cmd_arb)

    p_sumarb = sub.add_parser("sumarb", help="intra-market sum-to-1 rebalancing arb (report-only)")
    p_sumarb.add_argument("--min-edge", type=float, default=3, help="min net edge in cents (default 3)")
    p_sumarb.add_argument("--limit", type=int, default=20, help="max opportunities")
    p_sumarb.add_argument("--json", action="store_true", help="dump opportunities as JSON")
    p_sumarb.set_defaults(func=cmd_sumarb)

    p_comb = sub.add_parser("comb", help="combinatorial arb: ladder monotonicity + winner/margin (report-only)")
    p_comb.add_argument("--min-edge", type=float, default=2, help="min net edge in cents for winner/margin (default 2)")
    p_comb.add_argument("--min-vol", type=float, default=0.0, help="min volume per leg for ladder scan")
    p_comb.add_argument("--json", action="store_true", help="dump violations as JSON")
    p_comb.set_defaults(func=cmd_comb)

    p_cal = sub.add_parser("calibrate", help="calibration report")
    p_cal.set_defaults(func=cmd_calibrate)

    p_res = sub.add_parser("resolve", help="check for resolved markets")
    p_res.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
