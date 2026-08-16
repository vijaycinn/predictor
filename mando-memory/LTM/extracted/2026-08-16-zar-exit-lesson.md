---
tags: [dream, extracted, kalshi, lesson]
date_extracted: 2026-08-16
source_sessions: [weekly-order-review 2026-08-09_06-17-02, kalshi.db trades#17]
status: applied
---
# ZAR exit lesson — first live order sold before resolution, −7.5% margin

## Durable fact
The FIRST live Kalshi order (ZAR buy 1@0.59, Aug 1) was exited pre-resolution at 0.58 (`closed_manual`); market resolved YES at 0.99. Realized −$0.0441 on $0.59 invested = **−7.5% margin**, leaving +$0.393 on the table. Exit was the ONLY margin-relevant decision that week; entry mechanics were fine.

## Why it matters (recurrence evidence)
Rule 6 (ride to resolution, no stop-loss) and rule 6b (91c+ take-profit) already exist — but this is the live proof that breaking them costs money even at $1 stakes. Any pre-resolution exit below the 91c threshold needs an explicit VJ direction or a logged rationale; exits carry no reason field today (data gap).

## Applied action
- `Kalshi/learnings.md` — added lesson entry under "Market behavior": no pre-resolution exit unless 91c+ TP or explicit VJ direction (ZAR 2026-08-02, −$0.0441, −7.5% margin).
- NOT applied: codifying "log exit rationale in DB (new column)" — code change, flagged for VJ.

## Verbatim evidence
- "EXIT 0.58 — **THE margin killer**. Sold a position that resolved YES at 0.99. Left +$0.393 on table (0.59 → 1.00 win). Converted a certain winner into −$0.044."
- "MARGIN OF PROFIT: −7.5% | win rate: n/a (exited pre-resolution)"
