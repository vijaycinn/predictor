# VJ Hard Rules — Prediction Market Agent

Authoritative rule set. If code conflicts with this file, this file wins — fix the code.
Last updated: 2026-08-02 (post-Donski incident).

## Mission — THE ONLY SUCCESS METRIC IS MARGIN OF PROFIT (VJ 2026-08-02)

Sole purpose: **MAXIMIZE PROFITS.** Win rate is vanity; profit is the job.
Every decision, rule, scan, and execution exists to grow margin of profit.
Use Karpathy-style techniques to analyze METRIC vs DECISION continuously:
for each decision, trace its effect on profit margin; hypothesize what
drives the gap between decision and outcome; propose the smallest fix that
improves the metric; measure again. Fine-tune relentlessly. A losing trade
that follows the process is data, not failure. A winning trade that broke
the process is luck, not skill — both get analyzed.

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
5. **Maker depth pricing.** Rest on best bid level >= `maker_depth_cents` (2) below
   reference with size >= `maker_min_volume` (100) using full bid/ask ladders.
   **VOLUME-PEAK RULE (VJ 2026-08-02)**: ALWAYS follow the volume — the market
   leans where the money sits, not where market makers bait. Choose the level
   at the size-weighted center of mass of the qualifying cluster (collective
   intelligence), NOT the highest fillable level. Thin top-of-book bids are
   bait; the wall of size is the real lean. Drop levels >2 stddev from the
   peak, pick the level closest to the volume-weighted mean (ties → cheaper).
   Fallback: 50% nudge inside book. Never cross for fills when maker possible.
5b. **WALL GATE — FULL LADDER, NEVER TOP-10 (VJ 2026-08-05, Ribecai lesson, HARD).**
   Limit may NOT rest more than `wall_tolerance_cents` (2) ABOVE the full-ladder
   volume-weighted wall (density mode: max neighborhood volume ±3c, trash floor
   0.25×ref). Above wall = overpay = RuntimeError (`risk.wall_check` runs in
   `LiveExecutor.execute` every path; `sig['override_wall_check']` = explicit
   VJ bypass only). MUST use `kalshi.get_orderbook_full(ticker)` (orderbook_fp,
   ALL levels) — PMXT `fetchOrderBook` truncates top-10 and hides the real wall
   (Ribecai 2026-08-05: top-10 wall 0.76, full ladder wall 0.65 → bid at 0.76 =
   11c overpay, filled). Place promptly from instruction-time book: in-play
   books move fast, a re-fetch shows a moved snapshot (wall 0.65 → 0.78 in
   minutes).
5. **Order TTL — DEFAULT 1 HOUR (VJ 2026-08-02), unless VJ overrides.** Resting
   orders default to **1 hour expiry** (`max_lifetime_hours: 1`) — the stale
   resting order is dead weight, re-evaluate often. VJ explicit instructions
   (e.g. "1h", "24h", "until close") override. Never exceed 24h absolute cap,
   and leave >= 20% of the event's remaining time: lifetime <= 0.8 ×
   hours_to_expiry. Long-dated research bets may extend on VJ instruction.
5a. **TIMED-EVENT TTL = EVENT START (VJ 2026-08-03, codified).** For markets
   tied to a timed event (earnings call, EO signing, match kickoff, data
   release), DEFAULT TTL = event start time — the Kalshi app's "until event
   starts" expiry option. Order rests until event begins, then expires.
   `ttl = event_start − now` (min 1h, cap 24h, NO 0.8× decay — the event IS
   the expiry). Plain 1h default still applies to untimed/continuous markets.
   Origin: PLTR/GRAB/SNAP mention orders 2026-08-03 — 0.8× formula gave 5.2h,
   would expire 1.5h before the 21:00Z call; VJ set 8h to survive to start.
6. **$1/trade cap.** `risk.max_trade_usd: 1.0`. No margin ever (code asserts).
   Position cap per config. No stop-loss — ride to resolution.
6b. **TAKE-PROFIT — 91c+ EXIT (VJ 2026-08-09, Sabalenka lesson, HARD).** Live
   sports position whose market YES price reaches **≥0.91** → place reduce_only
   IOC sell at the bid wall, lock the profit. Do NOT ride a 91c+ winner to
   resolution. Rationale: at ≥91c, sell EV ≈ ride EV minus variance; the 5-8%
   blowup tail turns +45c locked into -45c (Sabalenka 2×@0.46 → decider loss,
   $1.84 swing). Winner-side only — this is NOT a stop-loss; rule 6 (ride
   losers) unchanged. Mechanics (verified live 2026-08-02): reduce_only
   requires IOC, omit expiration_time, selling YES = side NO (body ask),
   exit price = full-ladder bid wall (`kalshi.get_orderbook_full`), NOT the
   stale quote endpoint. Scale-out optional (sell half @91c, ride half).
   Threshold 91c = one-way; no re-entry below.
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
9. **VENUES (VJ 2026-08-05, HARD): "execute in polymarket" = polymarket.us
   ONLY.** Tradeable venues = Kalshi + polymarket.us. The worldwide venue
   (polymarket.com) is REFERENCE/TRUTH ONLY — its prices feed edge/arb math,
   NEVER place orders there. Label venue when comparing (PM.com = truth
   anchor, PM.us = tradable, Kalshi = execution venue #1).
10. **POLYMARKET = TRUTH ANCHOR, ARB = SELL-ONLY ON KALSHI (VJ 2026-08-04).**
   Polymarket is the better reflection of market truth — bigger, global, pioneer
   venue. PM price = truth. Kalshi = execution venue only.
   - **ARB DEFINITION (VJ, restated 2026-08-04):** when Kalshi price diverges
     from Polymarket price, evaluate **ONLY options to SELL on Kalshi**.
     The edge = Kalshi rich vs PM truth → SELL the Kalshi side (sell YES /
     buy NO at the rich price). Capturing overpricing, never buying the
     cheap side.
   - **NO BUY-SIDE CAPTURE.** Buying Kalshi YES because it's "cheap vs PM"
     is NOT the arb play — that's a directional bet, not skew capture.
     If Kalshi is NOT rich vs PM on a side, there is no sell opportunity → SKIP.
   - Sell mechanics: sell YES = place NO bid at the rich level. Win prob for
     the sell = 1 − PM-implied YES prob (PM = independent source, rule 7).
     Only sell when PM-implied YES prob < Kalshi sell price (edge positive).
   - Kalshi rich vs PM (e.g. BTC 60K one-touch 0.49/0.50 vs PM 0.45/0.46):
     sell YES at 0.50 (buy NO), edge = 0.50 − 0.46 = +4c.
   - PM-implied fair = PM bid/ask mid. Never hold a sell that prices below
     PM-implied YES prob.
9b. **POLYMARKET US = EXECUTION VENUE #2 (VJ 2026-08-05).** New US-regulated
  account (Ed25519 API keys, env `POLYMARKET_API_KEY`/`POLYMARKET_SECRET_KEY`).
  ALL the same rules apply: limit-only, win floor ≥50% from independent source,
  YES ≤40c band, ≤10% raise, full-ladder wall gate, $1/trade cap, per-buy
  approval, TTL (1h default / event-aware), no margin, no stop-loss.
  Execution = `scripts/pmus_cli.py order --place` (routes through
  `PolymarketUSExecutor` = same `risk.pre_flight_check` + `risk.wall_check`
  + `check_risk_limits` as Kalshi). pmxt is ANALYSIS ONLY for this venue.
  Polymarket US gateway (gateway.polymarket.us, no auth) = market data;
  api.polymarket.us = trading. Sports (NFL/MLB/tennis) heavy; prices tick
  0.001; `{value, currency}` object shape on px/bestBid/bestAsk.
9c. **PM.US TRADING FREEZE (VJ 2026-08-05, HARD).** NO orders on polymarket.us
  until its volume proves real. Observation: July CPI YoY >3.3% strike showed
  0.3 shares traded ($18.60) with OI 4,247 — quote-only market, no real
  liquidity; Kalshi had the only real book (20K NO wall). PM.us listing prices
  can be stale/unpriced → unexecutable + unreliable as fill reference. Analysis
  and quote reads ALLOWED (gateway no-auth); order placement FORBIDDEN.
  Revisit when a candidate market shows sustained volume (e.g. sports markets
  per rule 9b may qualify; CPI-style macro listings do not yet).
11. **Favorite categories**: T20/cricket, crypto (BTC/ETH targets ≤1mo), economic
    (Fed/CPI/jobs), politics, WTA/tennis. Skip in-play micro-edge chases unless
    user explicitly calls live shots.
12. **PRICE FILTER ≠ EDGE.** Cheap markets (sub-40c) are NOT automatically tradeable.
    No research/current-state bias = no trade = SKIP. A 2c YES on a 2% chance is a
    lottery ticket with no edge, not an opportunity (Filiz/Young/Zhukov losses).

## Workflow rules

13. **Never claim ready without execution proof** (EXISTS ≠ WORKS). Verify fills
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
17. **GEOPOLITICAL UPDATES — DeItaone feed (VJ 2026-08-02).** For geopolitical /
    macro updates that move oil, gas, Fed, or election markets, rely on the
    latest tweets from https://x.com/DeItaone (sorted newest). Source of truth
    for breaking geo/macro news. Fallback: web_extract on the profile. Applies
    to all macro-news-driven analysis. xurl CLI not installed yet — fetch via
    web_extract or install xurl when access needed.
18. **GEO-TRADES WINDOW — 7pm CST ONLY (VJ 2026-08-02).** Geopolitical
    choke-point incidents (Hormuz, Suez, straits) → oil ▲, gold ▲, VIX ▲,
    risk-OFF trades; de-escalation → inverse. Analyze Kalshi opportunities
    from geopolitical reads ONLY at 7pm CST (after-hours, especially Sunday
    PM — the post-move sets the tone for the week). Unless instructed, do NOT
    do geo analysis at other times. Feed: xurl @DeItaone (installed at
    /data/.hermes/home/.local/bin/xurl, auth verified).
    **TRUMP = BIGGEST MOVER (VJ 2026-08-02)**: market-moving tweets from the
    US president (via DeItaone) dominate — his ceasefire/deal words cool
    oil/commodities/commerce; his strike/tariff/threat words spike them.
    Trump tweets weighted 3x in direction score (★ in scan output).
19. **WEEKLY ORDER REVIEW — Sun 1am CT (VJ 2026-08-02).** Every Sunday 1am CT,
    pull order history for the week before the previous Sunday, evaluate the
    ONLY success metric: **MARGIN OF PROFIT**. If margins are poor and losses
    come from MECHANICS/understanding, produce an easy-to-follow caveman-style
    engineering report on what failed + how to improve, in Karpathy
    autoresearch style (state → analyze → hypothesize → fix proposal).
    **Implementation changes ONLY on VJ approval** — the review proposes, VJ
    disposes. Tool: scripts/weekly_review.py + agent report.

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

- **2026-08-05 Polymarket US bootstrap (VJ new account)**: account + API keys
  created (polymarket.us/developer, Ed25519 key ID + base64 secret). Auth
  verified live (`GET /v1/portfolio/positions` 200). pmxt's `PolymarketUS`
  class is INCOMPATIBLE — it signs EIP-712 with an ETH private key; Polymarket
  US needs Ed25519 `{ts}{method}{path}` signing. pmxt = ANALYSIS ONLY for
  polymarket_us. Native client `predictor/polymarket_us.py` + gated executor
  `PolymarketUSExecutor` (same pre_flight/wall/risk gates as Kalshi) +
  `scripts/pmus_cli.py`. Order shape validated via preview; placement rejected
  400 code 3 with $0 balance = funding blocker, not wiring. Fund account to go
  live. Rate limits: 20 rps/key; 5s latency stopgap on orders = transient
  reject, DO NOT back off (pure cancels exempt).
- **2026-08-02 Donski**: approved 0.34 underdog (list price), match went in-play,
  book repriced to 0.93, order filled at 0.90. Three failures: fresh book used as
  reference, no band check, cancel landed after fill. Fixes: band guard (40c),
  raise guard (10%), limit-only assert, approved-price-in-sig discipline.
- **2026-08-02 Underdog batch**: 8 sub-40c tennis YES picks placed without
  research (Filiz 2c, Young 7c, Zhukov 1c, etc.) — all lottery tickets, most
  resolved worthless. Selection failure: price filter treated as edge. Fix:
  RULES rule 11 (price ≠ edge) + LIVE FLOOR rule 7 (≥50% win from current state).
- **2026-08-05 Ribecai wall**: VJ: "Buy 1x yes at buy wall". Top-10 PMXT
  snapshot showed wall 0.76; FULL ladder wall sat 0.65. Bid placed 0.76, filled
  0.76 = 11c overpay vs wall. Root cause: top-10 truncation + re-fetch before
  placement (book moved 0.65 → 0.76+ in-play). Fixes: rule 5b wall gate +
  `risk.wall_check` in executor + `get_orderbook_full` helper (orderbook_fp,
  all levels). VJ: "POOR EXECUTION! IGNORE EXTREME OUTLIERS, FOCUS ON VOL
  WEIGHTED WALL."
