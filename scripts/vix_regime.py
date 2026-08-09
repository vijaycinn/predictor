#!/usr/bin/env python3
"""VIX regime gate (VJ cheat code, 2026-08-09).

BUY zone  : VIX > 30  (panic/fear -> contrarian buy: cheap risk-on bets)
TRIM zone : VIX < 15  (complacency -> trim profits, don't chase)
NEUTRAL   : 15-30

Use as a FILTER on top of normal gates — never a standalone trade signal.
Direction logic for Kalshi/PM.us:
  VIX > 30  -> risk-OFF panic. Buy cheap recovery / bounce candidates
               (contrarian). Or sell the fear side if priced rich.
  VIX < 15  -> risk-ON complacency. TRIM open winners, raise cash,
               no new aggressive long entries into euphoria.
  NEUTRAL   -> normal hunt rules apply.

Usage:
  python3 scripts/vix_regime.py            # print regime
  python3 scripts/vix_regime.py --json     # machine-readable
"""
import argparse
import json
import urllib.request

VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"


def get_vix() -> float | None:
    req = urllib.request.Request(VIX_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    meta = (d.get("chart", {}).get("result") or [{}])[0].get("meta", {})
    px = meta.get("regularMarketPrice")
    return float(px) if px is not None else None


def regime(vix: float) -> str:
    if vix > 30:
        return "BUY"
    if vix < 15:
        return "TRIM"
    return "NEUTRAL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    vix = get_vix()
    if vix is None:
        print("VIX fetch failed")
        raise SystemExit(1)
    reg = regime(vix)
    if args.json:
        print(json.dumps({"vix": vix, "regime": reg}))
        return
    print(f"VIX {vix:.1f} -> {reg} zone")
    if reg == "BUY":
        print("Panic. Contrarian buy: cheap recovery/risk-on candidates. Fees low at extremes.")
    elif reg == "TRIM":
        print("Complacency. Trim winners, raise cash, no chasing euphoria.")
    else:
        print("Neutral. Normal hunt rules.")


if __name__ == "__main__":
    main()
