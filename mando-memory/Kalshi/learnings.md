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

## Related
- [[rules]]
- [[Predictor/experiment-log]]
