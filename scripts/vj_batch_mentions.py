#!/usr/bin/env python3
"""VJ-directed batch (2026-08-03): buy all 10 earnings-mention markets.
Limit at cluster VWAP, notional <= $1.20/order. Band override for
near-certain class (VJ explicit buy-all). TTL = 0.8 * hours_to_call so
orders survive to tonight's earnings call (LiveExecutor 1h default would
expire them before the event — bypass executor, keep pre_flight gate).
"""
import os, sys, uuid
sys.path.insert(0, '/data/workspace/predictor')

env_path = os.path.expanduser('~/.hermes/.env')
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

import yaml
from datetime import datetime, timezone
from predictor import kalshi, risk

with open('/data/workspace/predictor/config.yaml') as f:
    cfg = yaml.safe_load(f)

# (ticker, limit, count, approved_prob, note)
ORDERS = [
    ("KXEARNINGSMENTIONGRAB-26AUG03-DELI",  0.22, 5, 0.75, "Delivery Hero"),
    ("KXEARNINGSMENTIONSNAP-26AUG03-SPEC",   0.26, 4, 0.80, "Spectacles"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-COMM",   0.40, 3, 0.75, "Commercial Growth"),
    ("KXEARNINGSMENTIONSNAP-26AUG03-PERP",   0.10, 12, 0.65, "Perplexity"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-REVE",   0.89, 1, 0.97, "Revenue Guidance"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-SLOP",   0.70, 1, 0.92, "AI Slop"),
    ("KXEARNINGSMENTIONGRAB-26AUG03-WERI",   0.56, 2, 0.85, "WeRide"),
    ("KXEARNINGSMENTIONGRAB-26AUG03-FOOD",   0.58, 2, 0.85, "Foodpanda"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-MAVE",   0.88, 1, 0.97, "Maven"),
    ("KXEARNINGSMENTIONPLTR-26AUG03-GOVE",   0.14, 8, 0.52, "Government Contract"),
]

now = datetime.now(timezone.utc)
call = datetime(2026, 8, 3, 21, 0, tzinfo=timezone.utc)
# TTL must SURVIVE to resolution (call 21:00Z + buffer). Near-certain closeby
# class rides to 1.00 at resolution — orders alive at call time.
ttl_h = 8.0  # expires 22:2xZ, after 21:00Z call
print(f"call at 21:00Z ({max((call - now).total_seconds()/3600,0.1):.1f}h) | TTL {ttl_h:.1f}h (survives to resolution)\n")

for ticker, limit, count, approved, note in ORDERS:
    sig = {
        "condition_id": ticker,
        "side": "YES",
        "signal_id": f"vj-batch-{ticker.split('-')[-1].lower()}",
        "approved_price": approved,
        "override_price_band": True,
        "override_win_floor": False,
        "ev_calc": {"price_side": approved, "prob_side": approved},
    }
    notional = round(limit * count, 2)
    try:
        risk.pre_flight_check(sig, limit, cfg)
        resp = kalshi.place_order(ticker, "YES", float(count), float(limit),
                                  hours_to_expiry=0,
                                  max_lifetime_hours=ttl_h)
        order = resp.get("order") or resp
        oid = order.get("order_id") or resp.get("order_id")
        status = str(order.get("status", "resting")).lower()
        print(f"OK  {ticker} {note} | {limit:.2f}x{count} = ${notional:.2f} | {status} | {str(oid)[:12]}")
    except Exception as e:
        print(f"FAIL {ticker} {note} | {limit:.2f}x{count} = ${notional:.2f} | {e}")
