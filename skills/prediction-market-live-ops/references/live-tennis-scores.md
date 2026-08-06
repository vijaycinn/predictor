# Live Tennis — Format Rules, Score Sources, Win-Prob Modeling

VJ rule (2026-08-02): *"Remember to understand the rules for sport bets before
suggesting valid ones for Live options."* Format and live score drive the edge;
never suggest live tennis without checking both.

## Match format (drives everything)

| Event | Format | Sets to win |
|-------|--------|-------------|
| Men's Grand Slam (ATP majors) | Best of 5 | 3 |
| Men's non-GS (ATP Tour, Challengers, qualifiers) | Best of 3 | 2 |
| Women (all events) | Best of 3 | 2 |

Consequence for score-state edge:
- **Bo3, 1-0 set lead** → leader needs 1 set, opponent needs 2. Historically
  ~60-65% match win prob for the set-1 winner.
- **Bo5, 1-0 set lead** → much smaller edge (leader needs 2, opponent 3).
- Same score means different probabilities in Bo5 vs Bo3 — always confirm
  format before quoting a win prob from the score.
- Kalshi tickers: `KXATPCHALLENGERMATCH` (Bo3), `KXATPMATCH` (could be Bo3
  tour or Bo5 GS — check event), `KXWTAMATCH` (Bo3), set-winner series
  (`KXATPSETWINNER`, `KXWTASETWINNER`).

## Live score sources (verified 2026-08-02)

| Source | Status | Notes |
|--------|--------|-------|
| tennisstats.com `/h2h/<player-a>-vs-<player-b>-<id>` | ✅ works | Live set scores + game scores + match odds; find via web_search "players H2H" |
| Robinhood prediction-market event page | ✅ works | `robinhood.com/us/en/prediction-markets/tennis/events/<slug>/` shows live score + live prices + vol |
| ESPN scoreboard API `site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard` | ⚠️ main tour only | Returns **0 events** for Challenger qualifying — do not rely on it for qualifiers |
| Sofascore API | ❌ 403 | `api.sofascore.com` and `www.sofascore.com` both 403 without auth |

Workflow: web_search "`<playerA>` vs `<playerB>` live score" → tennisstats H2H
page or Robinhood event page carries the current set/game state.

## Score-state → win prob heuristic (Bo3, all else equal)

- 1-0 set lead: ~60-65% for leader
- 1-1 sets: ~50/50 (decider)
- 0-1 (trailing a set): ~35-40%
- Add rank/form tilt: tennisstats shows 2026 win%, last-12mo win%, Elo, H2H.
  Example Ribero (rank 733, 48.6% 2026) vs Rejchtman (rank 938, 31%):
  set-1 winner Ribero + rank edge → ~0.55-0.58, but trailing 1-4 in set 2
  pulls it back toward coin flip.

## Live coin-flip structural SKIP (VJ rules interaction)

Live match markets mid 0.46-0.54 are usually BOTH sides blocked:
- YES side > 40c band (max_buy_price_cents) → blocked unless override
- Underdog YES < 50% win floor → blocked
- NO side of favorite = betting underdog wins → NO prob < 50% → floor blocks

Ribero 0.54 / Rejchtman 0.46 (2026-08-02): clean SKIP. A near-50/50 live
match has no valid entry under band + floor unless VJ explicitly overrides
the band for live matches. SKIP is the correct answer — don't force it.

## Ribero pattern — the ONE legal live flip (WON +$1.20, 2026-08-02)

VJ bought RIB YES 2 @ 0.40 (app) while Ribero led 6-4, trailed 1-4* in set 2.
Fair (score+form) ~0.56, limit 0.40 → resolved YES @ 1.00, +$1.20.

The band gate checks the LIMIT price, NOT fair value. So a legal live flip =
**cheap side ≤0.40 AND fair (independent, from score+form) ≥0.50** — buy 56c
of probability at 40c. Scanner flags these `[BUYABLE]` (cheap_side <= 0.40).

Counter-example (SKIP): Andreev 0.77 fair 0.87 — equity side priced above
band; Rolland 0.23 fair 0.13 — cheap but genuinely losing. Seeding keeps the
favorite cheap (Ravel seeded higher → Andreev +10c edge) but band still
blocks. Don't force an override on these; present the card and let VJ decide.

## TTL by score state (VJ rule, RULES.md rule 8)

Live tennis order TTL follows score movement, NOT fixed 60m:
- set 1 early, ~50/50 → 30-60m
- mid-match, drifting → 15-30m
- price moved >10c from your limit → CANCEL, re-scan (window gone)
- 0.80+ match-point territory → don't chase

Cazacu lesson (2026-08-02): limit 0.40 sat resting while market ran 0.61→0.82
— unfillable dead weight. If a live order won't fill at the new price, cancel
and re-scan; a stale resting live limit is worse than no order.
