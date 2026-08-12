#!/usr/bin/env python3
"""exit_plan.py — V1 poll-based take-profit exit manager (rule 6b).

VJ 2026-08-09: daemon/WS overkill for V1. Poll pattern instead:
  1. Read open Kalshi positions (BOTH directions)
  2. For each, compute take-profit exit order (91c default)
  3. Check if an exit order already rests on the book for that ticker
  4. If missing -> place it. Idempotent: re-running never duplicates.

Exit semantics (rule 6b, threshold = 0.91 default):
  - LONG (qty>0, bought YES): exit = SELL YES @ threshold  (resting ask)
    Fills when YES reaches 91c -> profit locked.
  - SHORT (qty<0, bought NO): exit = BUY YES @ (1 - threshold) (resting bid)
    Fills when NO reaches 91c (YES at 9c) -> profit locked.
  Winner-side only. NOT a stop-loss; losers ride to resolution (rule 6).

Usage:
  python3 scripts/exit_plan.py                     # dry-run: show plan only
  python3 scripts/exit_plan.py --place             # place missing exit orders
  python3 scripts/exit_plan.py --min 0.95 --ttl-h 48 --place
  python3 scripts/exit_plan.py --once --place      # same as --place
"""
import argparse
import os
import sys

def _repo_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here.endswith("scripts") and os.path.basename(os.path.dirname(here)) == ".hermes":
        repo = "/data/workspace/predictor"
        return repo if os.path.isdir(os.path.join(repo, "predictor")) else None
    return os.path.dirname(here)

REPO = _repo_path()
if REPO:
    sys.path.insert(0, REPO)

from predictor import kalshi  # noqa: E402


def load_env():
    for line in open("/data/.hermes/.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def open_positions():
    """qty>0 = YES long (BUY side), qty<0 = NO long / short YES (SELL side)."""
    out = []
    for p in kalshi.get_positions():
        ticker = p.get("ticker", "")
        qty = float(p.get("position_fp") or 0)
        if qty == 0:
            continue
        cost = float(p.get("total_traded_dollars") or 0)
        out.append({"ticker": ticker, "qty": qty, "side": "BUY" if qty > 0 else "SELL",
                    "entry_cost": cost})
    return out


def resting_exit_exists(ticker, position_side):
    """True if we already have a resting EXIT-direction order on this ticker.

    position_side: 'LONG' (qty>0, bought YES) or 'SHORT' (qty<0, bought NO).
    LONG exit = resting SELL YES (side no/ask) → locks profit at 0.91.
    SHORT exit = resting BUY YES (side yes/bid at ~0.09) → locks NO at 0.91.
    An ENTRY-direction resting order does NOT count as an exit:
    - side yes (buy) on a LONG = leftover entry bid, NOT an exit (KXCPINDEX
      08-10: buy-YES@0.12 masked a missing 0.91 exit).
    - side no (sell) on a SHORT = leftover entry ask, NOT an exit."""
    try:
        orders = kalshi.get_orders(status="resting")
    except Exception as e:
        print(f"  resting check ERR {ticker}: {str(e)[:80]}")
        return True  # fail closed: don't duplicate on uncertainty
    for o in orders:
        if o.get("ticker") != ticker:
            continue
        # Kalshi V2 canonical form: SELL YES = side=yes, action=sell.
        # Checking `side` alone is wrong (bb2d220 bug 08-12): LONG exits
        # were never matched -> cron placed a dupe every 12h tick.
        # Match on action instead: sell closes LONG, buy closes SHORT.
        action = (o.get("action") or "").lower()
        if position_side == "LONG":
            if action == "sell":
                return True  # resting SELL YES = exit for long
        else:
            if action == "buy":
                return True  # resting BUY YES = exit for short
    return False


def plan(threshold, ttl_h):
    """Build exit plan. Returns list of (ticker, qty, side, exit_side, limit, exists)."""
    rows = []
    for p in open_positions():
        ticker, qty = p["ticker"], p["qty"]
        pos_side = "LONG" if qty > 0 else "SHORT"
        exists = resting_exit_exists(ticker, pos_side)
        if qty > 0:  # LONG: sell YES at threshold
            rows.append((ticker, qty, "LONG", "SELL_YES", threshold, exists))
        else:        # SHORT: buy YES at 1-threshold to close
            rows.append((ticker, qty, "SHORT", "BUY_YES", round(1 - threshold, 2), exists))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", action="store_true", help="place missing exit orders (default dry-run)")
    ap.add_argument("--min", type=float, default=0.91, help="take-profit threshold (default 0.91)")
    ap.add_argument("--ttl-h", type=float, default=24.0, help="resting exit TTL hours (default 24)")
    ap.add_argument("--once", action="store_true", help="alias for --place (single pass)")
    ap.add_argument("--quiet", action="store_true", help="cron mode: silent when all-skip, print only placements/errors")
    args = ap.parse_args()
    place = args.place or args.once

    load_env()
    rows = plan(args.min, args.ttl_h)
    if not args.quiet:
        print(f"exit plan — threshold {args.min:.2f}, TTL {args.ttl_h:.0f}h, "
              f"{'PLACE' if place else 'DRY-RUN'}")
    placed = []
    for ticker, qty, side, exit_side, limit, exists in rows:
        if exists:
            if not args.quiet:
                print(f"  {side:5} {qty:>8.2f} {ticker} — exit already resting, skip")
            continue
        if exit_side == "SELL_YES":
            desc = f"SELL YES @ {limit:.2f} (locks profit if YES reaches {limit:.2f})"
        else:
            desc = f"BUY YES @ {limit:.2f} (locks profit if NO reaches {1-limit:.2f})"
        if place:
            try:
                # selling YES = side NO; buying YES = side YES
                kside = "NO" if exit_side == "SELL_YES" else "YES"
                resp = kalshi.place_order(ticker, kside, abs(qty), limit,
                                          hours_to_expiry=0, max_lifetime_hours=args.ttl_h)
                oid = (resp.get("order") or resp).get("order_id")
                print(f"  PLACED {side:5} {qty:>8.2f} {ticker} — {desc} id={oid}")
                placed.append(oid)
            except Exception as e:
                print(f"  ERR {ticker}: {str(e)[:120]}")
        else:
            print(f"  WOULD {side:5} {qty:>8.2f} {ticker} — {desc}")

    if args.quiet:
        # watchdog: emit ONLY when something happened (placed orders or errors)
        if placed:
            print(f"exit-plan: {len(placed)} orders placed, {len(rows)} positions checked")
    else:
        print(f"\n{len(placed)} orders placed, {len(rows)} positions checked.")
        if not place:
            print("Dry-run only. Re-run with --place to execute.")


if __name__ == "__main__":
    main()
