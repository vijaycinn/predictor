---
name: run-exit-plan
description: "Manually run take-profit exit plan (rule 6b): scan Kalshi open positions both directions, place missing 91c+ exits. Invoke: 'run exit plan', 'exit plan', 'take profit', 'lock profits', 'place exit orders'."
version: 1.0.0
author: Mando
tags: [prediction-markets, kalshi, exits, take-profit, risk]
---

# run-exit-plan — manual take-profit exit plan (rule 6b)

Invoke when VJ says: "run exit plan", "exit plan", "take profit", "lock
profits", "place exit orders", "set up exits on my positions".

Manual, approval-gated flow. NEVER auto-place without VJ's 👍.

## Why (VJ 2026-08-09, Sabalenka lesson)

Riding a 91c+ winner to resolution = variance bet. Sabalenka 2×@0.46 rode to
decider loss (−$0.92 vs +$0.92 locked = $1.84 swing). Rule 6b: exit at 91c+.
Kalshi has no trigger/OCO — a resting limit IS the conditional order.
Poll-based V1 chosen over daemon/WS (VJ 2026-08-09): idempotent, cron-friendly.

## Manual run flow (4 steps)

1. **Dry-run**: `python3 scripts/exit_plan.py` (from `/data/workspace/predictor`)
   → shows plan: every open position (both directions), exit order to place,
   or "already resting, skip".
2. **Present to VJ** as CAVEMAN CARD list, one line per position, marker:
   - `#pos 👍 LONG 2.00 KXFEDDECISION-26SEP-H0 — SELL YES @ 0.91`
   - `#pos 👎 SHORT -1.00 KXGOLDMON-... — BUY YES @ 0.09`
   Legend: 👍 = place exit, 👎 = skip this one.
   VJ replies 👍/👎 per line or "all" / "skip X".
3. **Place on approval**: `python3 scripts/exit_plan.py --place` places ALL
   missing exits. For partial (VJ skipped some), place manually via
   `kalshi.place_order` or delete the ticker from consideration — simplest is
   `--place` for all-approved, or run with a per-ticker filter if added later.
4. **Verify**: `get_orders(status="resting")` — confirm each exit rests.
   Idempotent by design: re-running never duplicates.

## Exit semantics (threshold 0.91 default, `--min` override)

- LONG (qty>0, bought YES): SELL YES @ 0.91 — resting ask, fills on touch.
- SHORT (qty<0, bought NO): BUY YES @ 0.09 — resting bid, fills when NO hits
  91c. Selling YES = side NO; buying YES = side YES (Kalshi V2).
- TTL: default 24h (`--ttl-h`); timed events → TTL to event start (rule 5a).

## Rules (hard)

- **Winner-side only.** Take-profit, NOT stop-loss. Losers ride (rule 6).
  Never place exit below entry as loss-cut.
- Threshold 0.91 one-way, no re-entry below.
- Only qty≠0 positions qualify; zero-qty ghosts skipped.
- Fail closed: resting-check error → skip ticker (no dupes on uncertainty).

## Verified (2026-08-09, live)

- 13 positions scanned both directions; 12 exits placed + verified resting.
- LONG sell YES @ 0.91 (`no_px 0.09`), SHORT buy YES @ 0.09 (`no_px 0.91`).
- Idempotent: re-run placed 0 new. KXCPINDEX skipped (exit already existed).

## Related

- `prediction-market-live-ops` — exits (reduce_only IOC), TAKE-PROFIT section,
  WS fill callback (V2 push upgrade, verified).
- `scripts/exit_plan.py` — the V1 poll script (repo source of truth; cron copy
  pattern `~/.hermes/scripts/` if ever cron'd).
- `scripts/take_profit.py` — dual-mode variant (IOC when wall≥91c else resting).
- `scripts/exit_watcher.py` — WS fill watcher (V2 candidate).
