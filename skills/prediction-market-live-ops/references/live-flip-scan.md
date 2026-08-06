# Live-option flip scan (VJ workflow, 2026-08-02)

Recurring cron watchdog that surfaces LIVE markets where odds can flip, for
quick 30m/60m TTL limit orders. Built after VJ asked for live tennis/MLB
flip candidates that Kalshi's 2h scan loop never surfaces.

## Cron

- Job: `live-flip-scan` (id 60dc2f20624f), schedule `*/30 * * * *`, no_agent=true.
- Script: **`/data/.hermes/scripts/live_flip_scan.py`** — the scheduler's script
  dir (SKILL.md cron-dir lesson 2026-08-03: NOT `~/.hermes/scripts/`, which
  expands to `/data/.hermes/home/.hermes/scripts/` on this box). Repo copy:
  `/data/workspace/predictor/scripts/live_flip_scan.py` — repo is source of
  truth, cron copy must be re-synced on edit.
- Delivery: origin chat, verbatim stdout. **Empty stdout = silent** (watchdog).
- Time gate INSIDE script: presents only 07:00-22:00 America/Chicago (VJ waking
  hours); `sys.exit(0)` silent otherwise. Cron runs 24/7; script self-gates.

## Flip-zone criteria (the "tight order range" definition)

Scans Kalshi binary markets from live-prone series prefixes:
`KXWTASETWINNER KXATPSETWINNER KXWTAMATCH KXATPMATCH KXATPCHALLENGERMATCH
KXWTACHALLENGERMATCH KXT20MATCH KXMLBGAME` for today's date events.

Keep only markets where:
- **mid 0.35-0.65** — neither side decided, either can flip. A 90c/10c market
  is dead, not a flip candidate.
- **spread <= 3c** — tight enough to rest a limit 1-2c off and still fill.
- **depth >= 200 contracts** (top-3 levels both sides, from raw orderbook_fp).
- **volume >= $2,000** dollar volume.
- Rank by flip_score = (1 - |mid - 0.50|) * min(vol, 500k)/500k.

Suggestion logic: buy the CHEAP side (the flip bet).
- mid <= 0.50 -> YES, limit = min(mid - 0.01, 0.40)
- mid > 0.50  -> NO,  limit = min(1 - mid - 0.01, 0.40)
- Band guard (40c) applies to suggested limits; floor 0.01.
- **BUYABLE flag** (Ribero pattern, added 2026-08-02): if cheap_side <= 0.40,
  mark `[BUYABLE]` and boost flip_score +0.15. Band gate checks the LIMIT
  price, not fair value — a 56c-fair bet rested at 0.40 is the legal live flip
  (Ribero WON +$1.20 doing exactly this).

## Output format — CAVEMAN CARDS, not tables (VJ 2026-08-02)

VJ rejected the wide table output ("Skip table as it doesn't render in a way
to make it easily to understand"). Script prints one compact card per market
or raw rows for the agent to reformat as cards. Card shape:
```
**PLAYER A vs PLAYER B — <event> | Bo3 | Clay**
TREND: A ▲▲▼ | B ▼▼▲        (▲ win / ▼ loss, last 5-7)
SCORE: Set 1: A 6-4 ✅ | Set 2: A 1-4* (break down)
MARKET: A 0.53/0.54 ($51k) | B 0.46/0.47 ($37k)
EST: A 0.56 | EDGE +2c
ACTION: SKIP — band >40c / floor <50%
```

## Guardrails (unchanged, enforced at execution not in script)

- Identification only — never auto-trades. VJ picks by table row number.
- Real orders still pass `pre_flight_check`: limit-only, 0-40c band,
  <=10% raise above approved, win-floor >=50% from CURRENT state.
- 30m/60m TTL is the *suggested* order lifetime for flip plays — set
  `hours_to_expiry` in features so `min(24h, 0.8*hte)` = 30-60 min
  (hte 0.625-1.25h), or pass explicit lifetime.

## Verified sample (2026-08-02 12:52 CT)

Found 58 flip-zone markets. Top: PHI/BAL MLB (mid 0.57), Zheng/Kecmanovic
(mid 0.41/0.58, $500k), Miami/NYM MLB (0.52), WSH/ATL MLB (0.56),
Pegula/Eala DC final (0.39/0.61, $440k).

## Pitfalls

- Kalshi MVE parlay markets (KXMVESPORTSMULTIGAMEEXTENDED...) embed player
  names in ticker and pollute naive name searches — exclude MVE via
  `mve_filter=exclude` or prefix whitelist.
- Set-winner markets repricing: mid 0.05-0.95 = in play; 0.90+ = set nearly
  decided. Don't suggest near-terminal sets as flips.

### RESOLVED matches can still appear in the flip scan (hit live 2026-08-03)

Scanner flagged Bartunkova vs Andreescu AND Boulter vs Cross as live flips —
both matches were ALREADY OVER (Bartunkova won; Cross won 7-6 7-5). The
scan only checks price/depth/volume, not match state. BEFORE presenting any
live-tennis candidate, confirm the match is actually in progress via a score
source (flashscore/tennisstats/Robinhood). A resolved-market "flip" is a
trap: you'd be bidding on a fixed outcome. If the score page shows final or
a winner, drop the row.

### Interrupted matches — market stays active, price gaps on resume

Zheng vs Kecmanovic (Montreal R128, 2026-08-03): rain-interrupted at 1-1
sets, decider 0-0. Kalshi market did NOT close — status active, close
extended (~Aug 16), expected_expiration stays at original estimate but the
market keeps trading until resumption. Price moved 17c toward Zheng
(0.56 → 0.73) on rain/resume news while the score was frozen. For
interrupted matches:
- Confirm the interruption (rain = ATP/WTA site news), resume time unknown.
- TTL must cover the unknown window — timed-event rule with generous floor
  (12-14h), NOT the 30-60m flip TTL.
- Price moves on NO new score (market reads resumption/momentum). Re-check
  thesis at resume, not at placement.
- Mando's rank-edge thesis (Kecmanovic 0.40: rank 62 vs 113 + set-1 winner)
  was repriced to Zheng 0.73 — market disagreed. Position still placed at
  0.31 per VJ direction; ride-and-track, don't average down on a gap.
