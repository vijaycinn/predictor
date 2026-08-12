# Kalshi V2 order canonical forms — side vs action (dupe-exit bug 2026-08-12)

## The bug

`resting_exit_exists` in exit_plan.py (bb2d220, 08-10 "direction-aware" patch)
checked `side == "no"` to detect an existing LONG exit (SELL YES @ 0.91).
**It never matched** because Kalshi V2 canonicalizes SELL YES as
`side=yes, action=sell`, NOT `side=no`.

Result: exit-plan-maintain cron (every 12h) placed a fresh LONG exit every
tick → 8 identical resting pairs (BTC×4, CPINDEX, CRYPTOSTRUCTURE, FED×2),
placed 12h apart. SHORT exits were unaffected (check `side=="yes"` matched
BUY YES canonical form). Fixed 08-12: match `action` not `side`.

## Canonical forms (what get_orders returns)

| Intent                    | side   | action | yes_price |
|---------------------------|--------|--------|-----------|
| SELL YES (close LONG)     | yes    | sell   | 0.91      |
| BUY YES (close SHORT)     | yes    | buy    | 0.09      |
| BUY YES (open LONG entry) | yes    | buy    | e.g. 0.12 |

Key: `side` says WHICH contract the order touches; `action` says buy/sell.
Two orders with identical side can be opposites (sell-to-close vs buy-to-open
both appear side=yes). **Dedup logic MUST use action**: sell closes LONG,
buy closes SHORT. `side` alone is ambiguous.

Related trap: the order create BODY uses `side: bid|ask` (bid = buy YES,
ask = buy NO / sell YES) — different vocabulary from the returned object's
`side: yes|no` + `action: buy|sell`. Don't mix the two representations.

## Dupe audit recipe (ran live 08-12, 8 groups found)

```python
from collections import Counter
orders = kalshi.get_orders(status="resting")
c = Counter((o.get("ticker"), o.get("side"), o.get("action"),
             o.get("yes_price_dollars")) for o in orders)
dupes = {k: v for k, v in c.items() if v > 1}
# keep the order with LATER expiration_time per ticker, cancel the rest
```

Cleanup: cancel via `kalshi.cancel_order(order_id)`; verify resting count
drops to one per ticker and `dupe groups left: 0`.

## Regression guard

- Re-run `python3 scripts/exit_plan.py` (dry-run) after any dedup change:
  all positions must print "exit already resting, skip", `0 orders placed`.
- If a cron maintains exits, a watchdog line "N orders placed" where N>0 on
  a quiet day = dedup regression, not success.
