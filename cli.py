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
    conn = db.connect(args.db)
    llm_overrides = {}
    if args.llm_overrides:
        llm_overrides = json.loads(Path(args.llm_overrides).read_text())
    from predictor.scanner import run_scan
    result = run_scan(conn, cfg, llm_overrides=llm_overrides, verbose=args.verbose)
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
    p_scan.add_argument("--verbose", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_status = sub.add_parser("status", help="positions + performance")
    p_status.set_defaults(func=cmd_status)

    p_cal = sub.add_parser("calibrate", help="calibration report")
    p_cal.set_defaults(func=cmd_calibrate)

    p_res = sub.add_parser("resolve", help="check for resolved markets")
    p_res.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
