#!/usr/bin/env python3
"""Take-profit scanner — rule 6b (VJ 2026-08-09, Sabalenka lesson).

Live sports position with YES bid wall >= 0.91 -> reduce_only IOC sell at the
bid wall, lock profit. Winner-side only; NOT a stop-loss.

Usage:
  python3 scripts/take_profit.py               # scan + report only (dry-run default)
  python3 scripts/take_profit.py --place       # place reduce_only IOC sells
  python3 scripts/take_profit.py --place --min 0.91 --half   # sell half, ride half

Rules enforced:
- YES positions only (NO positions ride per rule 6)
- exit price = full-ladder bid wall (get_orderbook_full), NEVER the stale quote
- reduce_only requires IOC; omit expiration_time (kalshi.place_order handles)
- selling YES = side NO (body ask) — place_order normalizes
- no re-entry below threshold (one-way)
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


def bid_wall(ticker):
    """Vol-weighted center of mass of the qualifying bid cluster (density mode)."""
    book = kalshi.get_orderbook_full(ticker)
    levels = book.get("yes_dollars") or []  # [[price,size],...] ASCENDING
    if not levels:
        return None, None
    # trash-floor: drop lottery bids < max(0.05, 0.25*top)
    top = float(levels[-1][0])
    floor = max(0.05, 0.25 * top)
    qual = [(float(p), float(s)) for p, s in levels if float(p) >= floor and float(s) > 0]
    if not qual:
        return None, None
    # density mode: max neighborhood volume ±3c
    best_lvl: float = 0.0
    best_vol = -1
    for p, s in qual:
        vol = sum(s2 for p2, s2 in qual if abs(p2 - float(p)) <= 0.03)
        if vol > best_vol:
            best_lvl, best_vol = p, vol
    wall = best_lvl
    # VWAP of wall neighborhood for fill reference
    nbr = [(p2, s2) for p2, s2 in qual if abs(p2 - wall) <= 0.03]
    vwap = sum(p2 * s2 for p2, s2 in nbr) / sum(s2 for p2, s2 in nbr) if nbr else wall
    return wall, vwap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", action="store_true", help="place reduce_only IOC sells (default: dry-run)")
    ap.add_argument("--min", type=float, default=0.91, help="YES bid-wall threshold (default 0.91)")
    ap.add_argument("--half", action="store_true", help="sell half the position, ride half")
    args = ap.parse_args()

    load_env()
    positions = kalshi.get_positions()
    hits = []
    for p in positions:
        ticker = p.get("ticker", "")
        qty = float(p.get("position_fp") or 0)
        if qty <= 0:
            continue  # YES long only
        try:
            wall, vwap = bid_wall(ticker)
        except Exception as e:
            print(f"{ticker}: wall fetch ERR {str(e)[:80]}")
            continue
        if wall is None:
            print(f"{ticker}: qty {qty:.0f} | no book")
            continue
        if wall >= args.min:
            hits.append((ticker, qty, wall, vwap))
            print(f"{ticker}: qty {qty:.0f} | bid wall {wall:.2f} (vwap {vwap:.2f}) | >= {args.min:.2f} TAKE PROFIT")
        else:
            print(f"{ticker}: qty {qty:.0f} | bid wall {wall:.2f} | below {args.min:.2f} — ride")

    if not args.place:
        print("\nDRY-RUN — nothing placed. Re-run with --place to execute.")
        return

    print()
    for ticker, qty, wall, vwap in hits:
        sell_qty = qty / 2 if args.half else qty
        # reduce_only IOC sell YES at bid wall (side NO = body ask)
        try:
            resp = kalshi.place_order(ticker, "NO", sell_qty, wall, reduce_only=True)
            print(f"SOLD {ticker} {sell_qty:.0f}@{wall:.2f} reduce_only: {resp}")
        except Exception as e:
            print(f"ERR {ticker}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
