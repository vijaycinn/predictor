---
tags: [predictor, experiments, log]
date_created: 2026-08-16
status: active
last_updated: 2026-08-16
---
# Experiment Log

Rolling log of predictor experiments. One H2 section per experiment, newest first. Use [[Templates/experiment]] skeleton.

## 2026-08 experiments

### 2026-08-16 — First live-order window review (weekly review 2026-08-09 + DB truth)
- Hypothesis: process-following live orders with $1/trade + gates would produce positive margin.
- Setup: live mode Kalshi, min gates (limit-only, win floor 50%, 40c band, edge ≥2c). Window Jul 26-Aug 2.
- Outcome: ZAR first live order −$0.0441 (−7.5% margin) — exited pre-resolution @0.58 while market resolved YES 0.99. Aug 2 window (next review): underdog challenger batch −$4.88 (ZHU −1.00, FIL −1.10, MAJ −0.90, KWONYOU −0.98, TORVAN −1.00, DON +0.10), WTI NO −0.82, Brent NO +0.92, VJ-app Ribero +$1.20.
- Root cause: (1) pre-resolution exit broke rule 6 (no rationale logged); (2) underdog batch = price-filter-≠-edge pattern already codified; (3) weekly_review.py resolution logic blind (`outcome_prices` mangled, `closed` always False, three window definitions) — reported "NO RESOLVED TRADES" falsely.
- Next action: exit-policy codification + weekly_review.py fix flagged for VJ (rule 19 report-only). Margin of profit stays the only metric.
- Evidence: [[LTM/extracted/2026-08-16-zar-exit-lesson]], [[LTM/extracted/2026-08-16-weekly-review-tooling-bugs]]

### 2026-08-16 — DB↔exchange reconciliation (data-integrity experiment)
- Hypothesis: local `trades` DB mirrored exchange positions.
- Setup: diff `db.open_positions()` vs `kalshi.get_positions()` + `get_fills(1000)`.
- Outcome: FAILED — 4 reported open vs 11 real. INNER JOIN markets dropped 13 positions; 10 trades size=0.0; 8 stale-finalized still OPEN; 2 exchange positions missing from DB; Donski mislabeled loss (actually WIN).
- Root cause: (1) `open_positions()` INNER JOIN cache table; (2) manual execution path skipped size capture; (3) resolution never reconciled stale OPEN; (4) retrospective written pre-resolution.
- Fix: LEFT JOIN; exit_reason column; size from fill count_fp; close 8 finalized; insert 2 missing; correct Donski. Now 11 == 11, zero drift.
- Lesson: reconcile DB against exchange EVERY weekly review — drift is silent and compounds. See [[Kalshi/learnings]] L1-L5.

### 2026-08-16 — Proposal gating behavior (DB census)
- 4,531 signals → 4,377 SKIP / 138 HOLD / 16 BUY; 6 proposals; 1 APPROVED (ZAR), 3 REJECTED (HOLD/SKIP not tradable), 1 REJECTED (spread boundary), 1 EXPIRED (undecided 15.5h). Engine is a disciplined no-trader; manual VJ fills are the actual trade flow. See [[LTM/extracted/2026-08-16-proposal-engine-quirks]].

## Logging convention
- One H2 per experiment: `## YYYY-MM-DD — <name>`
- Each entry: hypothesis, setup, outcome, root cause, next action.
- Win rate is vanity; MARGIN OF PROFIT is the only metric.
- Link per-run detail notes from `runs/` when needed.

## Related
- [[Kalshi/learnings]]
- `/data/workspace/predictor/RULES.md` (source of truth)
