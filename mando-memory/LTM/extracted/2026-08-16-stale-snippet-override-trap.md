---
tags: [dream, extracted, predictor, procedure]
date_extracted: 2026-08-16
source_sessions: [predictor-scan 2026-08-13 (Wrobleski), predictor-scan 2026-08-15_22-23-55 (Hayes)]
status: applied
---
# Stale web snippet override trap + both-gates-blocked = SKIP

## Durable fact
- Wrobleski 5+ Ks scan: an initial STALE web snippet said consensus line 4.5 → drafted a 0.50 override; live page verified 5.5 consensus (Under heavy, 9/15) → killed the bad override. **Never write an override from a stale snippet — verify the live source first.**
- Hayes 1+ hits (Aug 15): season .145 AVG but Statcast xBA .248 → actual says NO value, expected says YES value. YES side blocked by 40c band (mid 0.525), NO side blocked by min_win_prob 0.50 (P(NO) 0.465). Both gates block → **SKIP is correct**, no override.

## Why it matters (recurrence evidence)
The ≥5c override rule is the only thing standing between disciplined scans and noise trades. Two failure shapes seen in the same week: stale-data override (would have bought garbage) and divergent-metric market (both sides correctly gated). Scan outputs show "SKIP is correct" 30+ times across Aug 6-15 — the discipline holds; these two cases are the why.

## Applied action
- `Kalshi/learnings.md` — added "Scan discipline" entry: verify live source before override; both-sides-blocked = SKIP.
- No memory-tool edit (memory tool unavailable).

## Verbatim evidence
- "initial stale web snippet said 4.5 line → drafted 0.50 override; live page verified 5.5 consensus — killed bad override re-scan. No proposal ever created."
- "Actual results say NO value, expected stats say YES value. Divergence not clean in either direction. No override. Correct = SKIP."
