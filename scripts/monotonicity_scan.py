#!/usr/bin/env python3
"""Ladder monotonicity arb scanner (research 2026-08-06, EDGES.md §4).

For ladder series (KXGOLDMON monthly gold, KXWTIMAX/KXWTIMIN, KXBTCMAXMON/
KXBTCMINMON), P(>lower) >= P(>upper) by definition. When the market violates
it (ask_yes(lower) < ask_yes(upper)), buy lower YES + upper NO locks a
risk-free spread (one of the three regions always pays >$1).

NO-side pricing rule (research): NO ask (cost to BUY NO) = 1 - yes_BID,
NOT 1 - yes_ask. Using 1 - yes_ask understates cost by the full spread and
fabricates false arbs.

Report-only. Execution via normal gate (pre_flight + wall + approval).
"""
import sys
import os
import json
from datetime import datetime, timezone

def _repo():
    here = os.path.dirname(os.path.abspath(__file__))
    if here.endswith("scripts") and os.path.basename(os.path.dirname(here)) == ".hermes":
        repo = "/data/workspace/predictor"
        return repo if os.path.isdir(os.path.join(repo, "predictor")) else None
    return os.path.dirname(here)

REPO = _repo() or "/data/workspace/predictor"
sys.path.insert(0, REPO)

from predictor import kalshi  # noqa: E402
from predictor import fees as fees_mod  # noqa: E402

# series ticker prefixes -> (event-like fetch param, direction)
SERIES = [
    "KXGOLDMON", "KXWTIMAX", "KXWTIMIN", "KXBTCMAXMON", "KXBTCMINMON",
]

def parse_strike(ticker: str) -> float | None:
    """Extract numeric strike from KXGOLDMON-26AUG3117-T4251.99 -> 4251.99"""
    parts = ticker.split("-")
    for p in parts:
        if p.startswith("T") and p[1:].replace(".", "").isdigit():
            try:
                return float(p[1:])
            except ValueError:
                return None
    return None

def scan_series(series_prefix: str, min_volume: float = 0.0, limit: int = 300) -> list[dict]:
    """Fetch open markets for a series, find monotonicity violations."""
    try:
        d = kalshi.get_json("/markets", {"series_ticker": series_prefix, "status": "open", "limit": limit})
    except Exception as e:
        return [{"error": str(e)}]
    ms = d.get("markets", [])
    by_strike = {}
    for m in ms:
        if m.get("market_type") not in (None, "binary"):
            continue
        strike = parse_strike(m.get("ticker", ""))
        if strike is None:
            continue
        try:
            yes_ask = float(m.get("yes_ask_dollars") or 0)
            yes_bid = float(m.get("yes_bid_dollars") or 0)
            vol = float(m.get("volume_fp") or m.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        by_strike[strike] = {
            "ticker": m["ticker"], "yes_ask": yes_ask, "yes_bid": yes_bid,
            "volume": vol, "close": m.get("close_time"),
        }
    if len(by_strike) < 2:
        return []

    strikes = sorted(by_strike)
    violations = []
    for i in range(len(strikes) - 1):
        lower, upper = strikes[i], strikes[i + 1]
        lm, um = by_strike[lower], by_strike[upper]
        # P(>lower) must be >= P(>upper). Violation: ask_yes(lower) < ask_yes(upper)
        if lm["yes_ask"] < um["yes_ask"]:
            # Buy lower YES @ ask; buy upper NO @ 1 - upper yes_BID (NOT 1-yes_ask)
            cost_yes = lm["yes_ask"]
            cost_no = 1.0 - um["yes_bid"]
            combined = cost_yes + cost_no
            gross = 1.0 - combined
            # fees on both legs (upper NO is same market family: use its ticker)
            fee_yes = fees_mod.kalshi_fee(cost_yes, 1.0, lm["ticker"])
            fee_no = fees_mod.kalshi_fee(cost_no, 1.0, um["ticker"])
            slippage = 0.01
            net = gross - fee_yes - fee_no - slippage
            if min_volume and min(lm["volume"], um["volume"]) < min_volume:
                continue
            violations.append({
                "series": series_prefix,
                "lower_strike": lower, "upper_strike": upper,
                "lower_ticker": lm["ticker"], "upper_ticker": um["ticker"],
                "lower_yes_ask": round(cost_yes, 3),
                "upper_yes_bid": um["yes_bid"], "upper_yes_ask": um["yes_ask"],
                "no_ask_upper_1_minus_bid": round(cost_no, 3),
                "no_ask_upper_1_minus_ask_WRONG": round(1.0 - um["yes_ask"], 3),
                "combined": round(combined, 3),
                "gross_edge": round(gross, 4),
                "kalshi_fees": round(fee_yes + fee_no, 4),
                "net_edge": round(net, 4),
                "net_edge_pct": round(net * 100, 2),
                "close": um.get("close"),
            })
    violations.sort(key=lambda v: v["net_edge"], reverse=True)
    return violations

def main():
    args = sys.argv[1:]
    min_vol = 0.0
    only_series = None
    if args and args[0] != "--all":
        only_series = args[0].upper()
    if "--min-vol" in args:
        i = args.index("--min-vol")
        try:
            min_vol = float(args[i + 1])
        except (IndexError, ValueError):
            pass
    json_out = "--json" in args

    print(f"[{datetime.now(timezone.utc):%H:%M}Z] MONOTONICITY SCAN" +
          (f" series={only_series}" if only_series else " all-series") +
          (f" min_vol=${min_vol:.0f}" if min_vol else ""))
    print("=" * 72)
    found = 0
    for series in (SERIES if not only_series else [only_series]):
        viols = scan_series(series, min_volume=min_vol)
        if viols and "error" not in viols[0]:
            for v in viols:
                found += 1
                print(f"  {v['series']}: P(>{v['lower_strike']:.0f}) ask {v['lower_yes_ask']:.3f} "
                      f"< P(>{v['upper_strike']:.0f}) ask {v['upper_yes_ask']:.3f}")
                print(f"    BUY lower YES @ {v['lower_yes_ask']:.3f} + BUY upper NO @ {v['no_ask_upper_1_minus_bid']:.3f} "
                      f"(1 - yes_bid {v['upper_yes_bid']:.3f})")
                print(f"    combined ${v['combined']:.3f} gross {v['gross_edge']*100:.1f}c "
                      f"fees {v['kalshi_fees']*100:.1f}c net {v['net_edge']*100:.1f}c "
                      f"({'TRADE' if v['net_edge'] > 0 else 'no-edge'})")
                print(f"    tickers: {v['lower_ticker']} | {v['upper_ticker']}  close {v['close']}")
        elif viols and "error" in viols[0]:
            print(f"  {series}: fetch error {viols[0]['error'][:80]}")
    if found == 0:
        print("  no violations found")
    print("=" * 72)
    print(f"scan done: {found} violations")
    if json_out:
        out = []
        for series in (SERIES if not only_series else [only_series]):
            out.extend([v for v in scan_series(series, min_volume=min_vol) if "error" not in v])
        print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
