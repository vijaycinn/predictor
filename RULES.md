# VJ Hard Rules — Prediction Market Agent

Authoritative rule set. If code conflicts with this file, this file wins — fix the code.
Last updated: 2026-08-02 (post-Donski incident).

## Execution rules

1. **LIMIT ORDERS ONLY — NO MARKET ORDERS, EVER.**
   - `kalshi.place_order` hard-asserts a valid limit price (0 < p < 1).
   - `LiveExecutor.execute` refuses None/invalid limits. Never convert to market.
2. **Buy band: YES only 0–40c.** `execution.max_buy_price_cents: 40`.
   - Override only with explicit `override_price_band` flag (user-confirmed).
   - NO side exempt (buying NO at high price = buying YES cheap).
3. **Never pay >10% above approved price.** `execution.max_price_raise_pct: 10`.
   - Guard reference = `sig.ev_calc.price_side` or `sig.approved_price` (user-approved price, never the live book).
   - Resting BELOW approved is always fine — that's the maker edge.
   - Fail closed: raise, do not trade at stale/unapproved price.
4. **Maker depth pricing.** Rest on best bid level >= `maker_depth_cents` (2) below
   reference with size >= `maker_min_volume` (100) using full bid/ask ladders.
   **NORMAL-DISTRIBUTION PEAK (VJ 2026-08-02)**: price at the size-weighted mean
   cluster of the book, EXCLUDING outliers at the ends of the spectrum (a huge
   stale bid far below the cluster is a trap — don't chase it). Drop levels >2
   stddev below the peak, take best remaining.
   Fallback: 50% nudge inside book. Never cross for fills when maker possible.
5. **Order TTL = min(24h, 0.8 × hours_to_expiry).** Event-aware lifetime, applied
   exchange-side + DB + paper (three places, aligned).
6. **$1/trade cap.** `risk.max_trade_usd: 1.0`. No margin ever (code asserts).
   Position cap per config. No stop-loss — ride to resolution.
7. **NEVER BET IF OUTCOME PROBABILITY < 50%.** Applies to ALL bets (not just live).
   - The probability of each outcome must be individually established from an
     INDEPENDENT source: a different prediction market (Polymarket cross-venue =
     arb scenario) or verifiable research indicating propensity of that outcome.
   - Kalshi's own book alone is NOT a valid probability source (thin/stale books;
     Donski 0.34→0.90 incident). The independent prob goes in `sig.approved_price`
     / `ev_calc.price_side`; guard `min_win_prob: 0.50` refuses missing or <50% refs
     (`override_win_floor` only with explicit user confirmation).
   - Sub-50% outcomes are lottery bets — NEVER take them.
8. **LIVE BET TTL ALIGNED TO SCORE STATE (VJ 2026-08-02).** Tennis live orders:
   TTL is NOT fixed 60m — it follows how fast the score/odds move:
   - set 1 early, ~50/50 → 30-60m TTL
   - mid-match, price drifting → 15-30m
   - price moved >10c from your limit → CANCEL, re-scan (window gone)
   - match-point territory (0.80+) → don't chase
   A stale resting limit in live tennis is dead weight (Cazacu 0.61→0.82 while
   a 0.40 order sat unfillable, 2026-08-02). Format awareness: men's GS best-of-5,
   men's non-GS best-of-3, women best-of-3 — score-state edge depends on format.

## Market selection rules

8. **Crypto: ≤1 month to expiry only.** No wild 2-month+ price bets.
   (VJ: "I only am comfortable with crypto that is within a month.")
9. **Polymarket = sentiment/bias source** (global traders, wider sample than Kalshi).
   Research + Polymarket sentiment drives bias; ≥2% trend counts. Execution venue
   remains Kalshi (Polymarket live needs wallet+gas — not wired).
10. **Favorite categories**: T20/cricket, crypto (BTC/ETH targets ≤1mo), economic
    (Fed/CPI/jobs), politics, WTA/tennis. Skip in-play micro-edge chases unless
    user explicitly calls live shots.
11. **PRICE FILTER ≠ EDGE.** Cheap markets (sub-40c) are NOT automatically tradeable.
    No research/current-state bias = no trade = SKIP. A 2c YES on a 2% chance is a
    lottery ticket with no edge, not an opportunity (Filiz/Young/Zhukov losses).

## Workflow rules

12. **Never claim ready without execution proof** (EXISTS ≠ WORKS). Verify fills
    exchange-side (`/portfolio/positions` position_fp is ground truth), repair
    local DB (Kalshi returns `executed`, local may say RESTING).
13. **Every user-picked trade carries the approved price into sig** so guards
    have a reference (Donski 0.34→0.90 incident: approved underdog, stale book,
    filled at 0.90 — now blocked by band + raise guards).
14. **Report blockers immediately.** No hiding failures, no fabricated output.
15. **CONSOLIDATED PRE-FLIGHT GATE.** `risk.pre_flight_check(sig, limit, cfg)`
    runs ALL rules (limit-only, win floor, band, raise, no-margin) on every
    execution path. No path may skip a rule. Additive guard code in executors is
    discouraged — single source of truth in risk.py.
16. **SUGGESTION SUPPRESSION.** Markets with mid/prob < `min_win_prob` (0.50) are
    NEVER offered in scan shortlists or pick lists. If the rule says don't take
    it, don't suggest it — lottery tickets are not "options" (underdog batch
    2026-08-02: sub-40c list offered as choices, all lost).

## Retrospective — 2026-08-02 losses (drives rules above)

| Bet | Paid | State now | Root cause |
|-----|------|-----------|------------|
| Donski YES | 0.90 | 0.00 | Stale book repriced in-play; no price guard; no independent prob |
| Zhukov YES | 0.01 | 0.00 | Lottery: 1% outcome, no research |
| Filiz YES | 0.02 | 0.00 | Lottery: 2% outcome, no research |
| Young YES | 0.07 | 0.00 | Lottery: 7% outcome, no research |
| van Sambeek YES | 0.05 | 0.00 | Lottery: 5% outcome, no research |
| Majchrzak YES | 0.30 | 0.40 | Still live; sub-50% at entry anyway |

**Pattern**: every loser was <50% outcome probability (or stale-priced). No
independent probability source was consulted before placement. Suggestions were
made on price filter alone. Fixes: rule 7 (win floor all bets), rule 11 (price ≠
edge), rule 15 (pre-flight gate), rule 16 (suggestion suppression).

## Incident log

- **2026-08-02 Donski**: approved 0.34 underdog (list price), match went in-play,
  book repriced to 0.93, order filled at 0.90. Three failures: fresh book used as
  reference, no band check, cancel landed after fill. Fixes: band guard (40c),
  raise guard (10%), limit-only assert, approved-price-in-sig discipline.
- **2026-08-02 Underdog batch**: 8 sub-40c tennis YES picks placed without
  research (Filiz 2c, Young 7c, Zhukov 1c, etc.) — all lottery tickets, most
  resolved worthless. Selection failure: price filter treated as edge. Fix:
  RULES rule 11 (price ≠ edge) + LIVE FLOOR rule 7 (≥50% win from current state).
