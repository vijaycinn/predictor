---
tags: [kalshi, rules]
date_created: 2026-08-16
status: active
last_updated: 2026-08-16
---
# Rules Reference

Source of truth: `/data/workspace/predictor/RULES.md` — read it for full rules. This note = pointer + high-value summary only.

## High-value rules (summary)
- Rule 0: levels = MARGIN.
- Rule 9: ARB = sell-only on Kalshi (sell YES when PM-implied YES < Kalshi sell price).
- Rule 20: VIX gate — >30 BUY, <15 TRIM.
- Rule 21: never reprice VJ's zone without confirmation (pre-event STOP + ask; live flag).
- Rule 6b: 91c+ exits = run-exit-plan skill.
- Venue: Kalshi + PM.us only; PM.com = truth only.

## Weekly review
- Only metric = MARGIN OF PROFIT. Win rate = vanity.
- Karpathy metric-vs-decision.
- Sun 1am CT cron + CHANGES ONLY ON VJ APPROVAL.

## Related
- [[learnings]]
- [[Predictor/experiment-log]]
