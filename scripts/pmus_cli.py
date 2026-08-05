#!/usr/bin/env python3
"""pmus_cli.py — Polymarket US analysis + gated trading.

Analysis (gate-free reads): status | search | quote | scan | orders
Trading (SAME gates as Kalshi): order --dry-run (default) or --place.

The order path routes through predictor's PolymarketUSExecutor, which runs
the FULL Kalshi gate set: risk.pre_flight_check (limit-only, win floor >=50%
from independent source via --approved, YES <=40c band, <=10% raise, no
margin) + risk.wall_check (full-ladder volume wall) + risk.check_risk_limits
(position caps) + event-aware TTL. Fails closed — dry-run shows every gate
without touching the exchange; --place executes only if all pass.

pmxt is ANALYSIS ONLY for this venue (its PolymarketUS class signs EIP-712
with an ETH key — incompatible with Polymarket US Ed25519 API keys).

Usage:
  pmus_cli.py status
  pmus_cli.py search "bitcoin"
  pmus_cli.py quote <slug>
  pmus_cli.py scan [--category sports] [--limit 20]
  pmus_cli.py orders
  pmus_cli.py order --slug <slug> --side YES --qty 2 --price 0.35 \\
      --approved 0.55 [--ttl-hours 1] [--dry-run|--place]
  pmus_cli.py cancel --id <order_id> --slug <market_slug>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from predictor import polymarket_us as pmus  # noqa: E402
from predictor.config import load_config  # noqa: E402
from predictor import db  # noqa: E402

DEFAULT_DB = REPO / "data" / "predictor.db"
DEFAULT_CFG = REPO / "config.yaml"


def _fmt_ts(iso: str) -> str:
    if not iso:
        return "-"
    return iso[:16].replace("T", " ")


def cmd_status(args):
    print("=== BALANCES ===")
    try:
        for b in pmus.get_balances().get("balances", []):
            cur = b.get("currency", "?")
            print(f"  {cur}: balance={b.get('currentBalance')} buyingPower={b.get('buyingPower')} "
                  f"openOrders={b.get('openOrders')} pending={b.get('unsettledFunds')}")
    except pmus.ApiError as e:
        print(f"  balances ERR: {e}")
    print("=== POSITIONS ===")
    try:
        pos = pmus.get_positions()
        inner = pos.get("positions") or {}
        if not inner:
            print("  (none)")
        for slug, p in inner.items():
            print(f"  {slug}: {json.dumps(p)[:200]}")
    except pmus.ApiError as e:
        print(f"  positions ERR: {e}")
    print("=== OPEN ORDERS ===")
    cmd_orders(args)


def cmd_search(args):
    res = pmus.search(args.q, limit=args.limit)
    events = res.get("events") or []
    if not events:
        print("no events found")
        return
    for e in events[:args.limit]:
        start = _fmt_ts(e.get("startDate"))
        cat = e.get("category", "")
        print(f"{e.get('slug')} [{cat}] {start}\n  {e.get('title')}")
        for m in (e.get("markets") or [])[:3]:
            print(f"    market: {m.get('slug')} | {m.get('question', '')[:60]}")


def _mid(bbo_md: dict) -> float | None:
    def _v(x):
        if x is None:
            return None
        if isinstance(x, dict):
            return x.get("value")
        return x

    bb = _v(bbo_md.get("bestBid"))
    ba = _v(bbo_md.get("bestAsk"))
    try:
        if bb is not None and ba is not None:
            return round((float(bb) + float(ba)) / 2, 3)
        if bb is not None:
            return float(bb)
        if ba is not None:
            return float(ba)
    except (TypeError, ValueError):
        pass
    return None


def _px(x):
    """Unwrap a {value, currency} object to float, else plain float."""
    if isinstance(x, dict):
        x = x.get("value")
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cmd_quote(args):
    try:
        bbo = pmus.get_bbo(args.slug).get("marketData", {})
        book = pmus.get_book(args.slug).get("marketData", {})
    except pmus.ApiError as e:
        print(f"quote ERR: {e}")
        return
    bb, ba = _px(bbo.get("bestBid")), _px(bbo.get("bestAsk"))
    cur = _px(bbo.get("currentPx"))
    mid = _mid(bbo)
    print(f"SLUG: {args.slug}")
    print(f"STATE: {book.get('state')}")
    print(f"BBO: bid {bb} / ask {ba} | mid {mid} | last {cur}")
    print(f"DEPTH: bid {bbo.get('bidDepth')} / ask {bbo.get('askDepth')} | OI {bbo.get('openInterest')}")
    bids = book.get("bids", [])
    offers = book.get("offers", [])
    print(f"BOOK: {len(bids)} bid levels / {len(offers)} offer levels")
    for row, label in ((bids[:5], "BIDS"), (offers[:5], "ASKS")):
        if row:
            print(f"  {label}: " + " | ".join(f"{_px(x['px'])}x{x['qty']}" for x in row[:5]))


def cmd_scan(args):
    mkt = pmus.get_markets(limit=args.limit, closed=False, category=args.category)
    markets = mkt.get("markets") or []
    if not markets:
        print("no active markets (filter too narrow?)")
        return
    print(f"{len(markets)} active markets" + (f" [category={args.category}]" if args.category else ""))
    for m in markets:
        slug = m.get("slug")
        q = m.get("question") or m.get("description") or ""
        end = _fmt_ts(m.get("endDate"))
        sides = m.get("marketSides") or []
        px_yes = next((s.get("price") for s in sides if s.get("long")), None)
        px_no = next((s.get("price") for s in sides if not s.get("long")), None)
        print(f"{slug} | {q[:70]}")
        print(f"  end {end} | YES {px_yes} NO {px_no} | cat {m.get('category')}")


def cmd_orders(args):
    try:
        res = pmus.get_open_orders()
    except pmus.ApiError as e:
        print(f"open orders ERR: {e}")
        return
    orders = res.get("orders") or []
    if not orders:
        print("  (no open orders)")
        return
    for o in orders:
        px = o.get("price", {}).get("value")
        qty = o.get("leavesQuantity")
        meta = o.get("marketMetadata", {})
        print(f"  {o.get('id')} | {meta.get('slug')} | {meta.get('outcome')} | "
              f"px {px} leaves {qty} | {meta.get('title', '')[:40]} | gtt {_fmt_ts(o.get('goodTillTime'))}")


def _features_from_book(slug: str) -> dict:
    feats = {"hours_to_expiry": 0, "mid": None, "best_bid": None, "best_ask": None}
    try:
        bbo = pmus.get_bbo(slug).get("marketData", {})
        feats["best_bid"] = _px(bbo.get("bestBid"))
        feats["best_ask"] = _px(bbo.get("bestAsk"))
        feats["mid"] = _mid(bbo)
    except Exception:
        pass
    try:
        m = pmus.get_market(slug)
        end = m.get("endDate")
        if end:
            feats["hours_to_expiry"] = max(0.0, (time.mktime(time.strptime(end[:19], "%Y-%m-%dT%H:%M:%S")) - time.time()) / 3600)
    except Exception:
        pass
    return feats


def cmd_order(args):
    cfg = load_config(args.config)
    if args.ttl_hours:
        cfg.setdefault("execution", {})["order_ttl_hours"] = args.ttl_hours
    cfg["mode"] = "live"
    cfg["venue"] = "polymarket_us"

    conn = db.connect(str(args.db))
    feats = _features_from_book(args.slug)

    sig = {
        "condition_id": args.slug,
        "side": args.side,
        "action": "BUY",
        "approved_price": args.approved,
        "ev_calc": {"price_side": args.price, "prob_side": args.approved},
        "override_win_floor": False,
        "override_price_band": False,
        "override_wall_check": False,
    }

    from predictor import risk as risk_mod
    from predictor.executor import make_executor

    # GATE 1-5: consolidated pre-flight (limit-only, win floor, band, raise, no-margin)
    gate_errors = []
    try:
        risk_mod.pre_flight_check(sig, args.price, cfg)
        gate_errors.append("pre_flight: PASS")
    except RuntimeError as e:
        gate_errors.append(f"pre_flight: FAIL — {e}")

    # GATE 6: wall check (full ladder)
    ex = None
    try:
        ex = make_executor(conn, cfg)
        if not hasattr(ex, "_ladder"):
            gate_errors.append(f"wall_check: FAIL — executor for venue {cfg.get('venue')} has no ladder (wired venues: kalshi, polymarket_us)")
        else:
            ladder, _md = ex._ladder(args.slug, args.side)
            if ladder:
                risk_mod.wall_check(args.price, args.side, ladder, cfg)
                gate_errors.append(f"wall_check: PASS (wall ladder {len(ladder)} levels)")
            else:
                gate_errors.append("wall_check: SKIP (empty book)")
    except RuntimeError as e:
        gate_errors.append(f"wall_check: FAIL — {e}")
    except Exception as e:
        gate_errors.append(f"executor: ERR — {e}")

    # GATE 7: risk limits
    try:
        ok, reason = risk_mod.check_risk_limits(conn, sig, args.price * args.qty, cfg)
        gate_errors.append(f"risk_limits: {'PASS' if ok else 'FAIL — ' + reason}")
    except Exception as e:
        gate_errors.append(f"risk_limits: ERR — {e}")

    for g in gate_errors:
        print(g)

    blocked = any("FAIL" in g for g in gate_errors)
    print(f"\nRESULT: {'BLOCKED — no order placed' if blocked else 'GATES PASS'}")

    if blocked:
        return 1
    if args.dry_run:
        print(f"DRY-RUN: would place {args.side} x{args.qty} @ {args.price} on {args.slug} "
              f"(ttl={cfg['execution'].get('order_ttl_hours')}h, approved {args.approved})")
        return 0
    if ex is None:
        print("BLOCKED: executor unavailable")
        return 1

    # real placement — same executor as Kalshi approve path, same gates
    print(f"PLACING {args.side} x{args.qty} @ {args.price} on {args.slug} ...")
    try:
        trade = ex.execute(sig, args.qty, args.price, feats)
    except Exception as e:
        print(f"PLACEMENT REJECTED: {e}")
        return 1
    print(json.dumps({k: trade.get(k) for k in (
        "id", "condition_id", "side", "status", "order_status",
        "limit_price", "fill_price", "exchange_order_id", "ttl_expires_at",
    )}, indent=2, default=str))
    return 0


def cmd_cancel(args):
    try:
        resp = pmus.cancel_order(args.id, args.slug)
        print(f"cancel {args.id}: OK {resp}")
    except pmus.ApiError as e:
        print(f"cancel {args.id}: ERR {e}")
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(prog="pmus_cli", description="Polymarket US analysis + gated trading")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--config", default=str(DEFAULT_CFG))
    sub = p.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="balances + positions + open orders")
    p_status.set_defaults(func=cmd_status)

    p_search = sub.add_parser("search", help="search events/markets")
    p_search.add_argument("q")
    p_search.add_argument("--limit", type=int, default=8)
    p_search.set_defaults(func=cmd_search)

    p_quote = sub.add_parser("quote", help="BBO + book for a slug")
    p_quote.add_argument("slug")
    p_quote.set_defaults(func=cmd_quote)

    p_scan = sub.add_parser("scan", help="list active markets")
    p_scan.add_argument("--category")
    p_scan.add_argument("--limit", type=int, default=20)
    p_scan.set_defaults(func=cmd_scan)

    p_orders = sub.add_parser("orders", help="open orders")
    p_orders.set_defaults(func=cmd_orders)

    p_order = sub.add_parser("order", help="GATED order placement (dry-run default)")
    p_order.add_argument("--slug", required=True)
    p_order.add_argument("--side", required=True, choices=["YES", "NO"])
    p_order.add_argument("--qty", type=float, required=True)
    p_order.add_argument("--price", type=float, required=True)
    p_order.add_argument("--approved", type=float, required=True,
                        help="INDEPENDENT outcome prob (>=0.50) — win-floor gate")
    p_order.add_argument("--ttl-hours", type=float, default=1.0)
    g = p_order.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="show gates only (default behavior)")
    g.add_argument("--place", action="store_true", help="place if all gates pass")
    p_order.set_defaults(func=cmd_order)

    p_cancel = sub.add_parser("cancel", help="cancel an open order")
    p_cancel.add_argument("--id", required=True)
    p_cancel.add_argument("--slug", required=True)
    p_cancel.set_defaults(func=cmd_cancel)

    args = p.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
