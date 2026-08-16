---
tags: [dream, extracted, env-fact, flag]
date_extracted: 2026-08-16
source_sessions: [jobs.json, cron outputs 2026-08-01..08-15]
status: flagged
---
# Cron/config drift + broken jobs — needs VJ decision

## Durable fact
1. **predictor-scan prompt is stale vs config**: prompt says "max 2 open positions" and "edge < 2c"; config says `max_open_positions: 16` (raised 2026-08-02) and `min_edge: 0.03`. Real state Aug 15: **11 nonzero positions**, balance $46.03. Scan itself flagged it: "if 2 is the real cap, need VJ decision on which to trim. Current config permits 16."
2. **x-bookmarks-biweekly BROKEN**: `last_error: Script not found: /data/.hermes/scripts/fetch_bookmarks.py` — job never succeeded (last run Aug 15, status error).
3. **x-news-pull flaky**: 2× `TimeoutError ... idle for 600s` + "DeItaone feed: no tweets returned (xurl error?)" — feed auth/script intermittently fails; check xurl auth when feed empty.

## Why it matters (recurrence evidence)
Prompt/config drift silently changes risk posture — the operator believes "max 2 open" while 11 positions sit open under config 16. Broken bookmarks job = biweekly digest silently dead since creation. Both are exactly the kind of silent failure standing rule 3 forbids.

## Applied action
- Recorded here only. NO auto-apply — touches cron definitions + risk-config semantics. Flagged for VJ approval:
  - (a) reconcile predictor-scan prompt ↔ config: real max-open cap? real edge floor?
  - (b) create or remove `fetch_bookmarks.py` for x-bookmarks-biweekly.
  - (c) check xurl auth for DeItaone feed.

## Verbatim evidence
- "⚠️ Config `max_open_positions: 16` (raised 2026-08-02), but this cron prompt says **max 2** — we're at 11 nonzero. Flagging: if 2 is the real cap, need VJ decision on which to trim."
- "Script not found: /data/.hermes/scripts/fetch_bookmarks.py"
