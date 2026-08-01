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

    p_cal = sub.add_parser("calibrate", help="calibration report")
    p_cal.set_defaults(func=cmd_calibrate)

    p_res = sub.add_parser("resolve", help="check for resolved markets")
    p_res.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
