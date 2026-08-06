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

## THE METRIC — MARGIN OF PROFIT (VJ 2026-08-02, sole success metric)
Only success metric is **margin of profit** = P&L / invested. Win rate is
vanity; profit is the job. Report BOTH but judge by margin. Script headline:
`** MARGIN OF PROFIT: +X.X% on $Y invested **  <- THE metric`.

- Win: market resolved YES → P&L = qty × (1 − buy_price)
- Loss: resolved NO → P&L = −qty × buy_price
- Buy price from fill: `yes_price_dollars` for YES side, `no_price_dollars`
  for NO side (both strings, float() them).
- Resolution: `fetch_market_by_id(ticker)` → `outcome_prices[0] == 1.0` means
  YES won; `closed` flag = resolved.
- invested = Σ qty × buy_price over resolved trades; margin = P&L/invested.
- Apply Karpathy metric-vs-decision: trace each decision to its effect on
  margin, hypothesize the gap driver, propose smallest fix, measure again.
  A losing trade that followed process = data; a winning trade that broke
  process = luck. Both get analyzed.

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
