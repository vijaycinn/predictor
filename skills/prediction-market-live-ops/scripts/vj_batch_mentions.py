#!/usr/bin/env python3
"""VJ-directed multi-market batch order placement (Kalshi earnings-mention
style). Reads env KALSHI_API_KEY/KALSHI_PRIVATE_KEY (shell or ~/.hermes/.env),
places limit orders at wall levels with per-order notional cap.

Usage:
  python3 vj_batch_mentions.py            # place ORDERS list below
  python3 vj_batch_mentions.py --verify   # print resting orders w/ real fields

Pattern (VJ 2026-08-03): wall-level limit bids, count = floor(cap/price),
sig carries approved_price + ev_calc so pre_flight passes floor/raise gates,
override_price_band for the near-certain >40c class ONLY on VJ direction,
TTL = timed-event start (bypass LiveExecutor 1h default).

Field trap: resting order objects use initial_count_fp / remaining_count_fp /
no_price_dollars (YES price = 1 - no_price_dollars), NOT price/count.
"""
import os
import sys

sys.path.insert(0, "/data/workspace/predictor")

env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import yaml
from datetime import datetime, timezone

from predictor import kalshi, risk

# (ticker, limit, count, approved_prob, note)
# count = floor(notional_cap / limit); edit per batch.
NOTIONAL_CAP = 1.20
ORDERS = [
    # example 2026-08-03 earnings-mention batch
    ("KXEARNINGSMENTIONGRAB-26AUG03-DELI", 0.22, 5, 0.75, "Delivery Hero"),
    ("KXEARNINGSMENTIONSNAP-26AUG03-SPEC", 0.26, 4, 0.80, "Spectacles"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-COMM", 0.40, 3, 0.75, "Commercial Growth"),
]

EVENT_START_UTC = "2026-08-03T21:00:00Z"  # timed event start (call/signing); set per batch


def ttl_to_event():
    now = datetime.now(timezone.utc)
    ev = datetime.fromisoformat(EVENT_START_UTC.replace("Z", "+00:00"))
    return max(min((ev - now).total_seconds() / 3600.0, 24.0), 1.0)


def main():
    with open("/data/workspace/predictor/config.yaml") as f:
        cfg = yaml.safe_load(f)

    if "--verify" in sys.argv:
        orders = kalshi.get_orders(status="resting")
        for o in sorted(orders, key=lambda x: x.get("ticker", "")):
            if "EARNINGSMENTION" in o.get("ticker", "") or "TRUMPMENTION" in o.get("ticker", ""):
                yes_px = 1.0 - float(o.get("no_price_dollars", 0))
                cnt = float(o.get("initial_count_fp", 0))
                print(f"  {o.get('ticker')} bid {yes_px:.2f} x {cnt:.0f} = ${yes_px*cnt:.2f} "
                      f"| rem {o.get('remaining_count_fp')} | exp {o.get('expiration_time','?')[:16]}")
        return

    ttl_h = ttl_to_event()
    print(f"event TTL {ttl_h:.1f}h")
    for ticker, limit, count, approved, note in ORDERS:
        sig = {
            "condition_id": ticker,
            "side": "YES",
            "signal_id": f"vj-batch-{ticker.split('-')[-1].lower()}",
            "approved_price": approved,
            "override_price_band": True,  # VJ-directed batch only
            "override_win_floor": False,
            "ev_calc": {"price_side": approved, "prob_side": approved},
        }
        try:
            risk.pre_flight_check(sig, limit, cfg)
            resp = kalshi.place_order(ticker, "YES", float(count), float(limit),
                                      hours_to_expiry=0, max_lifetime_hours=ttl_h)
            order = resp.get("order") or resp
            oid = order.get("order_id") or resp.get("order_id")
            status = str(order.get("status", "resting")).lower()
            print(f"OK  {ticker} {note} | {limit:.2f}x{count} = ${limit*count:.2f} | {status} | {str(oid)[:12]}")
        except Exception as e:
            print(f"FAIL {ticker} {note} | {limit:.2f}x{count} | {e}")


if __name__ == "__main__":
    main()
