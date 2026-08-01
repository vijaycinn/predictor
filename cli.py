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
    positions = db.open_positions(conn)
    print(f"Open positions: {len(positions)}")
    total_cost = 0.0
    for p in positions:
        px = p["fill_price"] or p["limit_price"] or 0
        total_cost += px * p["size"]
        print(f"  {p['condition_id'][:10]} {p['side']:>3} x{p['size']:.0f} @ {px:.3f} | {p['question'][:60]}")
    print(f"Capital deployed: ${total_cost:.2f}")
    perf = learn.performance_summary(conn)
    print("Performance:", json.dumps(perf, indent=2))


def cmd_proposals(args):
    conn = db.connect(args.db)
    cfg = load_config(args.config)
    db.expire_stale_proposals(conn, cfg.get("approval", {}).get("ttl_hours", 2.0))
    pending = db.pending_proposals(conn)
    if not pending:
        print("No pending proposals.")
        return
    for p in pending:
        print(
            f"#{p['id']:>3} {p['side']:>3} x{p['size']:.0f} @ {p['limit_price']:.3f} "
            f"(${p['price_side'] * p['size']:.2f}) ev={p['ev_net']:.4f} conf={p['confidence']:.2f} | {p['question'][:55]}"
        )


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
                                    "order_status": "closed_manual"})
        print(f"#{tid}: closed {side} x{size:.0f} entry={entry:.4f} exit={exit_px:.4f} pnl=${pnl:.2f}")


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
    p_scan.add_argument("--venue", default=None, choices=["polymarket", "kalshi"], help="override venue from config")
    p_scan.add_argument("--verbose", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_status = sub.add_parser("status", help="positions + performance")
    p_status.set_defaults(func=cmd_status)

    p_prop = sub.add_parser("proposals", help="list pending trade proposals awaiting approval")
    p_prop.set_defaults(func=cmd_proposals)

    p_ap = sub.add_parser("approve", help="approve + execute proposals (re-verifies EV first)")
    p_ap.add_argument("ids", nargs="+", type=int, help="proposal IDs")
    p_ap.add_argument("--venue", default=None, choices=["polymarket", "kalshi"])
    p_ap.set_defaults(func=cmd_approve)

    p_rj = sub.add_parser("reject", help="reject proposals")
    p_rj.add_argument("ids", nargs="+", type=int, help="proposal IDs")
    p_rj.set_defaults(func=cmd_reject)

    p_ord = sub.add_parser("orders", help="list open/resting orders (lifecycle view)")
    p_ord.set_defaults(func=cmd_orders)

    p_cl = sub.add_parser("close", help="close an open position (paper: at book; live: reduce_only sell)")
    p_cl.add_argument("ids", nargs="+", type=int, help="trade IDs")
    p_cl.add_argument("--venue", default=None, choices=["polymarket", "kalshi"])
    p_cl.set_defaults(func=cmd_close)

    p_cx = sub.add_parser("cancel", help="cancel a resting order (live: also on exchange)")
    p_cx.add_argument("ids", nargs="+", type=int, help="trade IDs")
    p_cx.add_argument("--venue", default=None, choices=["polymarket", "kalshi"])
    p_cx.set_defaults(func=cmd_cancel)

    p_cal = sub.add_parser("calibrate", help="calibration report")
    p_cal.set_defaults(func=cmd_calibrate)

    p_res = sub.add_parser("resolve", help="check for resolved markets")
    p_res.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
