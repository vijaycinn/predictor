# Weekly order review — rule 19 (VJ 2026-08-02)

## Schedule & timezone
- Cron: `weekly-order-review`, `0 6 * * 0` (UTC) = **Sunday 01:00 America/Chicago**.
- Server clock is UTC. Sunday 1am CT = Monday? NO — same-day: 06:00 UTC Sunday.
  (CT = UTC−5 in CDT; 01:00 CDT = 06:00 UTC same day.)
- Verify with `TZ=America/Chicago date` before trusting a schedule.

## Script
`/data/workspace/predictor/scripts/weekly_review.py` (+ copy at
`/data/.hermes/scripts/weekly_review.py` for cron).

```bash
cd /data/workspace/predictor && python3 scripts/weekly_review.py
```

Output: target-week header → per-market fills (OPEN / RESOLVED WIN / RESOLVED
LOSS + P&L) → success rate + total P&L → failure-mode notes.

## Week-boundary math
Review run on Sun `now` covers the week BEFORE the previous Sunday:
- this_sun = start of current week (Sun 00:00 CT)
- prev_sun = this_sun − 7d
- target = [prev_sun − 7d, prev_sun)  (Sunday..Saturday, exclusive end)

Example: run Sun Aug 9 → covers Jul 26 (Sun) .. Aug 1 (Sat). Fills outside
the window are excluded; unresolved markets reported as OPEN.

⚠️ **Docstring is WRONG (verified 2026-08-09):** weekly_review.py's module
docstring claims "Sun Aug 9 covers Aug 2-Aug 8" — the CODE computes
[prev_sun−7d, prev_sun) = Jul 26-Aug 1, and code + this reference agree.
Trust `week_bounds()`, not the docstring. Consequence: the first live day
(Aug 2: BTC one-touch, Fed, challenger batch, Ribero win, WTI/Brent) falls
into the NEXT review's window, so the Aug 9 review legitimately shows ~0
resolved trades. Boundary note in the report labels that context.

## THE METRIC — MARGIN OF PROFIT (VJ 2026-08-02, sole success metric)
Only success metric is **margin of profit** = P&L / invested. Win rate is
vanity; profit is the job. Report BOTH but judge by margin. Script headline:
`** MARGIN OF PROFIT: +X.X% on $Y invested **  <- THE metric`.

- Win: market resolved YES → P&L = qty × (1 − buy_price)
- Loss: resolved NO → P&L = −qty × buy_price
- Buy price from fill: `yes_price_dollars` for YES side, `no_price_dollars`
  for NO side (both strings, float() them).
- **Resolution detection is BROKEN in the script (verified 2026-08-09):**
  `fetch_market_by_id` → normalized `outcome_prices` = `[0.0, 1.0]`
  placeholder for EVERY market (mangled by normalize_market) and `closed`
  always False even when `status=finalized` → script prints "NO RESOLVED
  TRADES" on a week with a finalized winner. TRUTH = raw
  `kalshi.get_json(f"/markets/{ticker}")` → `market["status"]=="finalized"`
  + `market["result"]` ("yes"/"no"). Always cross-check the raw fields when
  the script says nothing resolved.
- **Exit fills fall outside the window (verified 2026-08-09):** ZAR buy
  Aug 1 18:18 CT (in-window) exited Aug 2 12:36 CT (out-of-window) →
  realized −$0.0441 silently dropped; the lone buy would misreport as
  "OPEN" or a phantom resolved win. Match same-market opposite-side fills
  across the boundary for true round-trip P&L.
- invested = Σ qty × buy_price over resolved trades; margin = P&L/invested.
- Apply Karpathy metric-vs-decision: trace each decision to its effect on
  margin, hypothesize the gap driver, propose smallest fix, measure again.
  A losing trade that followed process = data; a winning trade that broke
  process = luck. Both get analyzed.

## Verified case study — ZAR (first live order, 2026-08-09 review)
- Bought YES 1@0.59 (Aug 1 18:18 CT — first real order ever), sold 1@0.58
  next day, market resolved YES at 0.99. Realized −$0.0441 = −7.5% margin
  on the week's only trade. Win rate n/a (exited pre-resolution).
- Root cause: pre-resolution exit within 1c of entry — round-trip fees
  (0.017+0.0171 = 3.4c on $0.59 = 5.8% drag) guarantee the loss. Rule 6
  (ride to resolution) is the default; take-profit only ≥0.91 (rule 6b).
- Mechanical secondary: local DB showed `size 0.0` on filled trades
  (18-23, 26-32) — STATUS TRAP family, DB ≠ exchange truth persists;
  exchange `/portfolio/positions` remains ground truth.
- Boundary: the documented Aug 2 batch (challenger underdogs −$4.88,
  Ribero +$1.20, WTI −0.82, Brent +0.92) belongs to the NEXT review
  (Aug 2-Aug 9 window); label it in the report, don't count it in margin.

## Mechanical vs thesis failure split
- MECHANICAL (process failure): high buy price (>0.30) that lost = stale book
  / no price guard / wrong band — fix the guard, not the thesis.
- THESIS (edge failure): sub-0.30 lottery or research-backed pick that lost =
  model wrong — refine research, not mechanics.

## Report format (Karpathy autoresearch style, caveman)
```
STATE:  target week, fills, success rate, P&L
ANALYZE: which trades lost, classify mechanical vs thesis
HYPOTHESIZE: root cause — which rule/guard was missing or violated
FIX PROPOSAL: concrete guard/config/code change
GATE: changes ONLY on VJ approval
```
No implementation in the cron run — the agent proposes, VJ disposes.
