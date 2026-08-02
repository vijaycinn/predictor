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

## Incident log

- **2026-08-02 Donski**: approved 0.34 underdog (list price), match went in-play,
  book repriced to 0.93, order filled at 0.90. Three failures: fresh book used as
  reference, no band check, cancel landed after fill. Fixes: band guard (40c),
  raise guard (10%), limit-only assert, approved-price-in-sig discipline.
- **2026-08-02 Underdog batch**: 8 sub-40c tennis YES picks placed without
  research (Filiz 2c, Young 7c, Zhukov 1c, etc.) — all lottery tickets, most
  resolved worthless. Selection failure: price filter treated as edge. Fix:
  RULES rule 11 (price ≠ edge) + LIVE FLOOR rule 7 (≥50% win from current state).
