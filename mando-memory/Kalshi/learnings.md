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

## 2026-08-16 fix batch (dream-flagged → VJ approved → DONE)
- weekly_review.py blind fixed: resolution now reads `status in (settled,finalized)` + `result` field, not `closed`/`outcome_prices` (those were live bid). Verified PASS.
- predictor-scan cron prompt aligned to config: max 16 open (was 2), min_edge 3c (was 2c). Config = source of truth.
- x-bookmarks-biweekly fixed: canonical `fetch_bookmarks.py` copied to `~/.hermes/scripts/`; no-fetch dry run OK (97 tweets).
- DeItaone feed hardened: retry + real error surfacing; live test OK (xurl auth was never broken).
- RULES.md rule 6: NO PRE-RESOLUTION EXIT codified (ZAR lesson) — only 91c+ TP (rule 6b) or explicit VJ direction.

## 2026-08-16 VJ explicit position control
- `python3 cli.py max-open <N>` — VJ sets cap, persists in `data/runtime.json` (gitignored, survives restarts).
- `check_position_cap` enforces: blocks new entries when open >= cap (verified: cap 3 blocks 4/3, cap 8 allows).
- `cli.py status` + `max-open` show `open X / cap Y` with runtime-override marker.
- predictor-scan cron reads cap dynamically — never hardcodes (was "16").
- RULES.md rule 6 documents the mechanism. Config fallback stays 16.

## 2026-08-16 DB↔exchange reconciliation (be-thorough pass)
- Root cause found: `open_positions()` used INNER JOIN markets → dropped 13 real positions (4 vs 17 in DB, 11 real). Fixed to LEFT JOIN. Now 11 DB == 11 exchange, zero drift both directions.
- 8 stale tennis/WTI/Brent trades still OPEN but finalized on exchange → CLOSED with correct pnl (Dondes WON +$0.10, Brent NO won +$1.10, rest losses). Exchange `result` field = truth.
- 2 positions on exchange missing from DB (gold T3451.99 NO, crypto-structure YES) → inserted.
- 10 trades had size=0.0 while exchange had real fills (BTC 2/5/8, Fed 3/2/11, Zhukov 100, Filiz 55, etc.) → repaired from exchange fills.
- `exit_reason` column added to trades + `cli.py close --reason` wired (rule 6 exit-rationale data gap closed).
- RULES.md retrospective Donski row corrected: was "0.00 loss", actually `result=yes` WIN (+$0.10). Repricing lesson unchanged.

## Lessons (durable, transferable — 2026-08-16 reconciliation pass)

### L1: INNER JOIN silently drops live positions
- **Root cause**: `open_positions()` JOINed `markets` — any OPEN trade missing a markets row vanished from the count. Reported 4 open, reality 11.
- **Pattern to avoid**: position/order counting that depends on a join to a cache table (`markets`). Cache misses become phantom-zero positions.
- **Correct pattern**: LEFT JOIN for anything counted (positions, orders, caps). Or count from `trades` alone, join only for display columns. Verify count against exchange (`get_positions()`) every reconciliation.
- **Class**: Kalshi STATUS TRAP family — local DB silently diverges from exchange truth. EXISTS ≠ WORKS. DB ≠ exchange.

### L2: Exchange `result`/`status` fields are truth, not your notes
- **Root cause**: RULES.md retrospective wrote Donski "0.00 loss" from an Aug-2 snapshot; exchange `result=yes` → actual WIN +$0.10.
- **Pattern to avoid**: persisting a resolved outcome from a mid-flight snapshot or memory. Retrospective tables written pre-resolution go stale silently.
- **Correct pattern**: resolution = `status in (settled, finalized)` + `result` field, fetched fresh from exchange. Reconcile retrospective tables against exchange before trusting P&L numbers. Notes are narrative; exchange is ledger.

### L3: Manual-execution path records size=0.0
- **Root cause**: manual `LiveExecutor` fills (VJ app buys) inserted trades with `size=0.0` while exchange carried real contract counts (2/5/8/100/55...). Proposal-gated path captured size; manual path didn't.
- **Pattern to avoid**: two execution paths writing trades with different field completeness. The gated path and manual path must record identical fields.
- **Correct pattern**: one `record_trade` path for all fills; size always from exchange fill `count_fp`, never defaulted. Reconcile `size` against fills on every weekly review.

### L4: Prompt/config drift silently changes risk posture
- **Root cause**: cron prompt said "max 2 open / 2c edge" while config said 16 / 3c — operator believes one cap, system enforces another. 11 positions open under the loose cap.
- **Pattern to avoid**: hardcoding policy numbers in cron prompts / scripts instead of reading config. Numbers rot in two places and drift.
- **Correct pattern**: single source of truth (config + `cli.py max-open` runtime override). Prompts/scripts read the value, never restate it. Any hardcoded policy number = drift bug waiting.

### L5: Exits without rationale are an un-auditable data gap
- **Root cause**: ZAR exit @0.58 (pre-resolution) carried no reason field — couldn't distinguish rule-breaking exit from VJ-directed exit.
- **Correct pattern**: `exit_reason` column + `cli.py close --reason`. Every close logs why (91c-TP / VJ-direction / resolved). No silent exits.

## Related
- [[rules]]
- [[Predictor/experiment-log]]
