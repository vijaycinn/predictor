---
tags: [dream, extracted, predictor, tooling, env-fact]
date_extracted: 2026-08-16
source_sessions: [weekly-order-review 2026-08-09_06-17-02]
status: flagged
---
# weekly_review.py resolution blindness — DB ≠ exchange truth

## Durable fact
`scripts/weekly_review.py` resolution detection is broken: uses normalized `outcome_prices` (mangled to `[0.0,1.0]` placeholder for ALL markets) + `closed` flag (always False even when `status=finalized`). It reported "NO RESOLVED TRADES" on a week that had a resolved loss. Raw `result`/`status` fields are truth. Window definitions disagree: docstring says "Aug 2-Aug 8", code computes Jul 26-Aug 1, skill text says Jul 26-Aug 2.

## Why it matters (recurrence evidence)
Same family as the Kalshi STATUS TRAP (`"executed"` ≠ `"filled"`): local DB silently diverges from exchange truth and tooling trusts the DB. Weekly review is the ONLY margin-of-profit measurement (rule 19) — blind resolution logic = blind P&L reporting.

## Applied action
- Recorded here + `Predictor/experiment-log.md` entry. Knowledge itself is safe (how to read truth: `status=="finalized"` + `result`, cross-check `/portfolio/fills`).
- NOT applied: the code fix (`weekly_review.py` resolve via raw status/result, kill `outcome_prices`/`closed` path; one-time DB size repair for trades 18-23/26-32) — flagged for VJ approval per rule 19 "report only".

## Verbatim evidence
- "weekly_review.py resolution logic is broken — uses normalized `outcome_prices` (mangled to `[0.0,1.0]` placeholder for ALL markets) + `closed` flag (always False even when `status=finalized`). It would report \"nothing resolved\" on a week with 6 resolved losses."
- "Script headline: \"NO RESOLVED TRADES\" — **wrong**, see ANALYZE #2"
