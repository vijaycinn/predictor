---
tags: [dream, extracted, kalshi, env-fact]
date_extracted: 2026-08-16
source_sessions: [predictor-scan outputs 2026-08-01..08-15, kalshi.db proposals#2-6 blocked_trades#1]
status: applied
---
# Proposal engine quirks — HOLD/SKIP not tradable, EXPIRED proposals, spread boundary

## Durable fact
- Engine action `HOLD`/`SKIP` → proposal auto-REJECTED even with positive EV ("action HOLD not tradable"). BTC dip ladder proposals (#2-4, Aug 2: 57.5K/55K/52.5K) all REJECTED this way — yet VJ manually bought the same ladder minutes later (57.5K 2@0.35, 55K 5@0.19, 52.5K 8@0.12, later 60K 2@0.45). Manual `LiveExecutor` path bypasses the proposal gate.
- Proposals expire 2h; an undecided proposal goes `EXPIRED` (gas NO #6, created Aug 12 22:36, expired Aug 13 14:08).
- Spread gate bites exactly at boundary: CPI #5 rejected `spread 0.040 > max 0.04`; gas #1 blocked at 0.070.
- Signal action distribution (4,531 signals): 4,377 SKIP / 138 HOLD / 16 BUY → engine almost never says BUY; proposal bar (edge ≥2c per cron prompt) is the binding constraint, not config `min_edge: 0.03` — prompt/config drift (see cron-config-drift extract).

## Why it matters (recurrence evidence)
Anyone reading proposals must know REJECTED ≠ bad idea (HOLD/SKIP not tradable = engine shape, not edge verdict) and EXPIRED ≠ declined. VJ's manual fills don't appear as proposals — always check `/portfolio/fills` + positions.

## Applied action
- `Kalshi/learnings.md` — added "Proposal engine quirks" entry under Market behavior.
- No memory-tool edit (memory tool unavailable in this environment).

## Verbatim evidence
- "action now HOLD (edge 0.026); action HOLD not tradable" (proposal #2 note)
- "No fills, no cancels, no new orders this cycle. Pending proposals: 0." + "11 nonzero positions on exchange: BTC dips (52.5K x8 @0.12, 55K x5 @0.19, 57.5K x2 @0.35, 60K x2 @0.45), Fed Sep (H0 YES x2 @0.42, H25 NO x3), Fed Oct C25 x11 @0.09, gold NO x3, crypto-structure x1.93" (2026-08-15 scan)
