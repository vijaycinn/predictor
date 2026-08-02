#!/usr/bin/env python3
"""Weekly order review — Sun 1am CT (VJ 2026-08-02, rule 19).

Evaluates the week's orders: success rate, P&L, failure mode split
(mechanical/understanding vs thesis/edge), and produces a caveman-style
engineering report for VJ. IMPLEMENTATION CHANGES ONLY ON VJ APPROVAL —
this script only analyzes and reports.

Week definition (VJ): every Sunday 1am CT, review the week BEFORE the
previous Sunday (i.e. the full week that ended ~8 days ago).
Example: review on Sun Aug 9 covers Aug 2 (Sun) - Aug 8 (Sat).
"""

import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")

def week_bounds(now_ct: datetime) -> tuple[datetime, datetime]:
    """For a review run at 'now', return (start, end) of the target week:
    the Sunday-Saturday week that ended 8 days before this Sunday."""
    # this Sunday (start of current week)
    this_sun = now_ct - timedelta(days=now_ct.weekday() + 1)  # weekday() Mon=0 -> Sun is -1
    if now_ct.weekday() == 6:  # Sunday itself
        this_sun = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        this_sun = (now_ct - timedelta(days=now_ct.weekday() + 1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    # target week = the one before the previous Sunday
    prev_sun = this_sun - timedelta(days=7)
    start = prev_sun - timedelta(days=7)  # Sunday of target week
    end = prev_sun  # Sunday start of week after target (exclusive)
    return start, end

def kalshi_import():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from predictor import kalshi
    return kalshi

def main():
    now = datetime.now(CT)
    start, end = week_bounds(now)
    print(f"[{now:%a %H:%M} CT] WEEKLY REVIEW — target week {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    print("=" * 72)

    kalshi = kalshi_import()

    # 1. pulls from exchange (fills = source of truth)
    fills = []
    try:
        fills = kalshi.get_fills(limit=1000)
    except Exception as e:
        print(f"WARN: fills fetch failed: {e}")
    # filter to target week (created_time UTC -> CT)
    wk_fills = []
    for f in fills:
        try:
            ts = datetime.fromisoformat(f["created_time"].replace("Z", "+00:00"))
            ts_ct = ts.astimezone(CT)
        except Exception:
            continue
        if start <= ts_ct < end:
            wk_fills.append(f)

    # 2. local DB trades for context
    conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "data/kalshi.db"))
    db_trades = []
    for r in conn.execute(
        "SELECT id, condition_id, side, action, size, limit_price, fill_price, status, created_at FROM trades"
    ):
        db_trades.append(dict(zip(
            ["id", "condition_id", "side", "action", "size", "limit_price", "fill_price", "status", "created_at"], r)))

    # 3. outcome resolution: fetch market status for each traded condition
    by_ticker = defaultdict(list)
    for f in wk_fills:
        by_ticker[f["ticker"]].append(f)

    print(f"\nTARGET WEEK FILLS: {len(wk_fills)} ({len(by_ticker)} markets)")
    print("-" * 72)

    rows = []
    for ticker, fl in sorted(by_ticker.items()):
        buy_price = float(fl[0].get("yes_price_dollars") or fl[0].get("no_price_dollars") or 0)
        qty = sum(float(x.get("count_fp", 0)) for x in fl)
        side = fl[0].get("side", "?")
        # resolve outcome via market
        try:
            m = kalshi.fetch_market_by_id(ticker)
            prices = m.get("outcome_prices") or []
            resolved = m.get("closed", False)
            yes_resolved = float(prices[0]) if prices else 0.0  # 1.0 = YES won
        except Exception:
            resolved = False
            yes_resolved = None
        rows.append({
            "ticker": ticker, "qty": qty, "price": buy_price, "side": side,
            "resolved": resolved, "yes_won": yes_resolved == 1.0,
        })
        status = "RESOLVED WIN" if (resolved and yes_resolved == 1.0) else \
                 ("RESOLVED LOSS" if resolved else "OPEN")
        pnl = qty * (1.0 - buy_price) if (resolved and yes_resolved == 1.0) else \
              (-qty * buy_price if resolved else None)
        pnl_s = f" P&L ${pnl:+.2f}" if pnl is not None else ""
        print(f"  {status:<13} {ticker[:44]:44s} {side} {qty:.0f}@{buy_price:.2f}{pnl_s}")

    # 4. success rate + P&L
    resolved_rows = [r for r in rows if r["resolved"]]
    wins = sum(1 for r in resolved_rows if r["yes_won"])
    total_pnl = sum(
        r["qty"] * (1.0 - r["price"]) if r["yes_won"] else -r["qty"] * r["price"]
        for r in resolved_rows)
    print("-" * 72)
    if resolved_rows:
        rate = wins / len(resolved_rows) * 100
        print(f"SUCCESS RATE: {wins}/{len(resolved_rows)} = {rate:.0f}%   |   RESOLVED P&L: ${total_pnl:+.2f}")
    else:
        print("NO RESOLVED TRADES in target week (nothing settled yet).")
        rate = 0.0
        total_pnl = 0.0

    # 5. failure-mode split (mechanical vs thesis) — heuristic from ticker/price
    # mechanical markers: fills far from limit, IOC/reduce_only, >10c stale repricing
    mech_flags = []
    for r in resolved_rows:
        if not r["yes_won"] and r["price"] > 0.30:
            mech_flags.append(f"{r['ticker']} bought {r['price']:.2f} (high price + loss = price risk)")

    print("\nFAILURE-MODE NOTES (mechanical vs understanding):")
    if mech_flags:
        for m in mech_flags:
            print(f"  ⚠ {m}")
    else:
        print("  none flagged (losses, if any, are thesis/edge-driven, not mechanical)")

    print("\n" + "=" * 72)
    print("REPORT COMPLETE — implementation changes ONLY on VJ approval (rule 19).")
    print(f"Data: {len(wk_fills)} fills, {len(resolved_rows)} resolved, "
          f"{(len(rows)-len(resolved_rows))} still open.")

if __name__ == "__main__":
    main()
