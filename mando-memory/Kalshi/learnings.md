---
tags: [kalshi, learnings]
date_created: 2026-08-16
status: active
last_updated: 2026-08-16
---
# Kalshi Learnings

Wins, losses, edge cases, recurring blind spots. One entry per lesson, newest first. Use [[Templates/lesson]] skeleton.

## Seed learnings (from RULES.md + trading history)

### Venue + truth
- Trade = Kalshi + PM.us ONLY. "Execute in polymarket" = PM.us.
- PM.com = truth only (reference, never execution).
- ARB = SELL-ONLY ON KALSHI: sell YES when PM-implied YES < Kalshi sell price (rule 9).

### Order rules
- Rule 0: levels = MARGIN.
- Rule 21: never reprice VJ's zone without confirmation (pre-event STOP + ask; live flag).
- 91c+ exits → run-exit-plan skill (rule 6b).

### Market behavior
- WALL GATE: full-ladder wall; PMXT truncates → kalshi.get_orderbook_full. Quote wall in direction.
- VIX gate rule 20: >30 BUY, <15 TRIM.
- Geo-trades: choke-points → oil▲ gold▲ VIX▲ risk-OFF; de-escal inverse. TRUMP = BIGGEST mover. 7pm CST only.

### Sources
- ESPN Cricinfo = definitive cricket source. County = scan default; CPL on VJ link drop.
- Live scores: sports-hub MCP.

## 2026-08-16 dream additions (evidence in LTM/extracted/)

### Exit discipline — ZAR lesson (first live order, 2026-08-02)
- ZAR buy 1@0.59 exited pre-resolution @0.58; market resolved YES 0.99 → −$0.0441, **−7.5% margin**, +$0.393 left on table. Exit was the only margin-relevant decision.
- Rule: NO pre-resolution exit unless (a) take-profit ≥91c (rule 6b) or (b) explicit VJ direction. Exits carry no reason field — data gap.
- Source: [[LTM/extracted/2026-08-16-zar-exit-lesson]]

### Proposal engine quirks (verified in kalshi.db)
- Action `HOLD`/`SKIP` → proposal auto-REJECTED even with positive EV ("action HOLD not tradable"). BTC dip ladder proposals rejected Aug 2 while VJ manually bought same ladder (57.5K@0.35, 55K@0.19, 52.5K@0.12, 60K@0.45) — manual `LiveExecutor` path bypasses proposal gate.
- REJECTED ≠ bad idea; EXPIRED ≠ declined (gas NO proposal #6 sat undecided 15.5h → EXPIRED). Proposals TTL 2h.
- Spread gate exact-boundary: CPI rejected `spread 0.040 > max 0.04`; gas blocked 0.070.
- Signal mix (4,531): 4,377 SKIP / 138 HOLD / 16 BUY — engine almost never says BUY.
- Source: [[LTM/extracted/2026-08-16-proposal-engine-quirks]]

### Scan discipline
- STALE SNIPPET TRAP: never override from a stale web snippet — Wrobleski 4.5-line snippet drafted 0.50 override; live page showed 5.5 consensus → killed. Verify live source first.
- Both-gates-blocked = SKIP: Hayes 1+ hit — actual (.145) says NO, xBA (.248) says YES; YES blocked by 40c band, NO by min_win_prob 0.50. Correct = SKIP.
- Source: [[LTM/extracted/2026-08-16-stale-snippet-override-trap]]

## Related
- [[rules]]
- [[Predictor/experiment-log]]
