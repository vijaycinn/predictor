---
name: predict
description: "Manual prediction-market trade hunt (Kalshi/Polymarket): scan shortlist, research edge, create proposals, approve. Use for 'hunt for a trade', 'best trade today', 'arb check'."
version: 1.1.0
author: Mando
tags: [prediction-markets, trading, kalshi, polymarket, ev, arb]
---

# predict — manual trade hunt

Invoke for: "hunt for a trade", "what should I trade", "best Kalshi trade",
"arb check", "check crypto/econ markets".

Project: `/data/workspace/predictor` (Python + SQLite, dual venue). CLI:
`cli.py scan|status|orders|proposals|approve|reject|close|cancel|arb|calibrate|resolve`.
Current config: `mode: live`, `venue: kalshi`, `max_trade_usd: 1.0`,
`max_open_positions: 2` (VJ set 2026-08-01).

## Hunt flow (5 steps)

1. **Shortlist**: `python3 cli.py --db data/kalshi.db scan --venue kalshi --shortlist /tmp/shortlist.json`
   Filter for VJ-relatable categories: T20/cricket, crypto (BTC/ETH price targets), economic (Fed/CPI/jobs), politics.
2. **Research**: web_search each candidate. Look for ≥5c divergence from market mid:
   - T20/cricket: ESPN Cricinfo = definitive source (VJ 2026-08-08) — team form, key player availability, pitch/toss, head-to-head, odds
   - Crypto: BTC/ETH price action, funding, liquidation levels vs market target
   - Economic: consensus forecasts vs market-implied prob (data release dates)
   - Sports props: player rate stats vs market price (B-R over ESPN)
3. **Override ONLY on ≥5c evidence**: write `{condition_id: prob_yes}` JSON.
   No evidence = no override = no trade. SKIP is correct.
4. **Proposals**: `scan --llm-overrides /tmp/overrides.json` (live mode creates PENDING proposals, never executes).
5. **Approve**: `python3 cli.py --db data/kalshi.db proposals` then `approve <id> --venue kalshi`.
   Approve re-checks book + EV, fails closed if edge faded.

## Proposal eval format (VJ 2026-08-05, HARD)

Every proposal presented to VJ MUST carry a decision marker: **👍 = approve/place,
👎 = reject/skip**. One line per proposal, marker first. CLI `proposals` prints:

```
#123 👍 YES x1 @ 0.130 ($0.13) ev=+4.2c conf=0.71 | AFFO will win the match?
👍 = APPROVE (place order) | 👎 = REJECT (skip)
```

Chat (Telegram) presentations of proposals use the same shape: `#id 👍/👎
SIDE xSIZE @ PRICE ($cost) ev=Xc conf=Y | question` then the legend line. VJ
replies with the emoji + id (or just approves/rejects). NEVER present a
proposal without 👍/👎 — the marker IS the decision interface.

## Hard rules (VJ, 2026-08-02)

- **NEVER BET IF OUTCOME PROB < 50%** (ALL bets, not just live). Prob must be individually established from INDEPENDENT source: Polymarket cross-venue price (arb) or verifiable research — Kalshi's own book alone is NOT valid. Carry it in `sig.approved_price`/`ev_calc.price_side`; guard `min_win_prob: 0.50` refuses missing/<50% (`override_win_floor` = explicit user confirm only). Sub-50% = lottery = never.
- **LIMIT ORDERS ONLY — NO MARKET ORDERS EVER.** `kalshi.place_order` hard-asserts a valid limit price (0<p<1); `LiveExecutor.execute` refuses None/invalid limits. Never convert to market.
- **YES band 0-40c** (`max_buy_price_cents`, incl live bets) + **never pay >10% above approved** (`max_price_raise_pct`; approved in sig, NEVER fresh book — Donski 0.34→0.90).
- **Maker depth pricing**: rest ≥2c below ref, ≥100 contracts depth (full bid/ask ladders).
- Live = `mode: live` + `venue: kalshi` only (Polymarket live needs wallet+gas).
- $1/trade cap, max open positions per config, per-buy approval (2h TTL, EV re-check, fails closed), NO MARGIN EVER (code asserts), NO stop-loss (ride to resolution).
- Price filter ≠ edge: cheap ≠ tradeable; no research/independent prob = SKIP.

## Venue rule (VJ 2026-08-05, HARD)

**"Execute in polymarket" = polymarket.us ONLY.** Tradeable venues: Kalshi +
polymarket.us. The worldwide venue (polymarket.com) is REFERENCE/TRUTH ONLY —
use its prices for edge/arb math, NEVER place orders there. Polymarket.us API
requires key headers; PMXT exchange name = `polymarket_us`. When comparing
prices, label the venue explicitly (PM.com = truth anchor, PM.us = tradable).

**PM.US TRADING FREEZE (VJ 2026-08-05, HARD):** NO orders on polymarket.us
until volume proves real. Observation: July CPI YoY >3.3% strike = 0.3 shares
traded ($18.60), OI 4,247 — quote-only, no real liquidity; Kalshi had the only
real book (20K NO wall). PM.us listing prices can be stale/unpriced →
unexecutable + unreliable as fill reference. Analysis/quote reads ALLOWED
(gateway no-auth); order placement FORBIDDEN. Revisit when candidate market
shows sustained volume (sports per rule 9b may qualify; macro CPI-style do
not yet).

## Polymarket = truth anchor, ARB = SELL-ONLY on Kalshi (VJ 2026-08-04)

Polymarket is the better reflection of market truth — bigger, global, pioneer
venue. Kalshi = execution venue only.

**ARB DEFINITION (VJ, restated 2026-08-04): when Kalshi price diverges from
Polymarket price, evaluate ONLY options to SELL on Kalshi.** The edge = Kalshi
RICH vs PM truth → SELL the Kalshi side (sell YES / buy NO at the rich price).
Capturing overpricing, never buying the cheap side.

- **NO BUY-SIDE CAPTURE.** Buying Kalshi YES because it's "cheap vs PM" is NOT
  the arb play — that's a directional bet, not skew capture. If Kalshi is NOT
  rich vs PM on a side, there is no sell opportunity → SKIP.
- Sell mechanics: sell YES = place NO bid at the rich level. Win prob for the
  sell = 1 − PM-implied YES prob (PM = independent source, rule 7). Only sell
  when PM-implied YES prob < Kalshi sell price (edge positive).
- Verified example 2026-08-04: Kalshi BTC 60K one-touch 0.49/0.50 vs PM
  dip-to-60K 0.45/0.46 → Kalshi 4c rich → SELL YES at 0.50 (buy NO), edge +4c.



## Hard rules (VJ, 2026-08-02)

- **NEVER BET IF OUTCOME PROB < 50%** — ALL bets. Prob from INDEPENDENT source (Polymarket cross-venue = arb, or verifiable research); Kalshi book alone invalid. Carry in `sig.approved_price`/`ev_calc.price_side`; `min_win_prob: 0.50` guard refuses missing/<50% (`override_win_floor` = user confirm only).
- **SUGGESTION SUPPRESSION**: sub-50% markets never offered in shortlist/pick lists. If we shouldn't take it, don't suggest it.
- **PRICE FILTER ≠ EDGE**: cheap ≠ tradeable; no research/independent prob = SKIP. Sub-40c list without research = losing pattern (underdog batch 2026-08-02).
- **CONSOLIDATED GATE**: `risk.pre_flight_check()` on every execution path — patch it, don't add one-off guards.

## Skip protocol (VJ 2026-08-03)

Before declaring SKIP on any market, run volume-weighted analysis + offer override:

1. Pull FULL order book — `kalshi.get_orderbook_full(ticker)` returns `orderbook_fp.yes_dollars`/`no_dollars` arrays of `[price,size]` ASCENDING, ALL levels. NEVER trust a top-10 snapshot (PMXT truncates; Ribecai 2026-08-05: top-10 showed wall 0.76, full ladder wall 0.65).
2. **DENSITY MODE, not top-cluster** (VJ re-fix 2026-08-03): the top-3c cluster can be thin bait (AFFO top cluster VWAP 0.178, vol 28) while the WALL sits deeper (0.13×104). Use the volume-peak rule from live-ops: sum sizes of levels within ±3c of each level, pick the MAX-neighborhood-volume level = center of mass. AFFO wall = 0.13, NOT 0.178.
3. VWAP of the wall neighborhood: `sum(price*size)/sum(size)` over the qualifying cluster (yes for buys, no for sells).
4. Percentile of our order target = share of resting volume priced at/below target.
   - target at wall → center percentile, high fill odds
   - target far below mass → low percentile, fills only on move
5. Report SKIP as: `SKIP — target 13c sits at wall (VWAP 13c, vol 104). Override?`
6. VJ override → place per his direction (bypasses in-play/band/sub-50 gates, see exception above).

**WALL GATE (VJ 2026-08-05, Ribecai lesson, HARD):** `risk.wall_check()` runs inside `LiveExecutor.execute` on every placement — limit may NOT rest more than `wall_tolerance_cents` (2) ABOVE the full-ladder vol-weighted wall. Bidding above the wall = overpay = RuntimeError. `override_wall_check` in sig = explicit VJ bypass only. Placement must also be prompt: an in-play book moves fast — compute wall from the book at instruction time, place immediately; a re-fetch can show a moved snapshot (Ribecai: wall 0.65 at instruction, 0.76+ by placement).

Origin: AFFO lesson 2026-08-03. Mando quoted top-cluster 0.178; VJ bid 13c at the wall ("volume showed concentration at that level"). Wall = truth, bait = noise.

## Polymarket US — execution venue #2 (2026-08-05)

VJ opened a Polymarket US account (US-regulated). Analysis + trading wired:

- **Auth**: Ed25519 sign `{ts}{method}{path}`, headers X-PM-Access-Key /
  X-PM-Timestamp / X-PM-Signature. Keys in /data/.hermes/.env:
  `POLYMARKET_API_KEY` (Key ID) + `POLYMARKET_SECRET_KEY` (base64 secret).
- **pmxt CANNOT trade this venue**: its PolymarketUS class signs EIP-712 with
  an ETH private key. pmxt = ANALYSIS ONLY. Native transport:
  `predictor/polymarket_us.py` (verified live).
- **Reads (no auth)**: gateway.polymarket.us — `/v1/markets`,
  `/v1/markets/{slug}/book`, `/v1/markets/{slug}/bbo`, `/v1/search?q=`,
  `/v1/events`. px/bestBid/bestAsk are `{value, currency}` objects — unwrap.
- **Trading (SAME gates as Kalshi, VJ rule)**: `scripts/pmus_cli.py order
  --slug S --side YES|NO --qty N --price P --approved A --dry-run|--place`.
  Routes through PolymarketUSExecutor = identical `risk.pre_flight_check` +
  `risk.wall_check` + `check_risk_limits` + event-aware TTL (GTD tif,
  maker-only PDI). Dry-run shows every gate; fails closed. Approved prob
  (independent source) required — win floor ≥50% enforced.
- Order shape: `{marketSlug, type: ORDER_TYPE_LIMIT, price:{value,currency},
  quantity, tif, outcomeSide, action, participateDontInitiate}`; GTD needs
  goodTillTime RFC3339. Preview endpoint `/v1/order/preview` validates
  without placing. 400 code 3 generic = exchange rejection (e.g. $0 balance).
- Rate limits: 20 rps/key. 5s latency stopgap on orders = transient reject,
  do NOT back off (pure cancels exempt).

## Gotchas

- **Approve flow dilutes manual bias**: `approve` re-checks EV with engine that blends llm_override at `llm_weight` (0.30) vs market 0.55 — a 9c research edge can come back as HOLD/SKIP and fail closed. For VJ-explicit picks, bypass: insert_proposal is not enough; place directly via `LiveExecutor.execute(sig, size, limit, feats)` with `sig.condition_id/side/ev_calc.price_side`. Then repair local trade status (exchange returns `executed`, local stays RESTING — set OPEN + fill_price manually).
- **Kalshi positions**: field is `position_fp` + `market_exposure_dollars`, NOT quantity_fp. status display shows x0 for filled trades (display bug, exchange is truth).
- **Maker depth strategy (VJ 2026-08-02)**: prefer_maker rests on best bid level ≥`maker_depth_cents` (2) below ref price with size ≥`maker_min_volume` (100), via full `bid_ladder`/`ask_ladder` in features. **VOLUME-PEAK RULE — FOLLOW THE MONEY, ALWAYS**: price at the size-weighted center of mass of the qualifying cluster, NOT the highest fillable level. Thin top-of-book bids are market-maker bait; the wall of size is the real lean. Drop >2 stddev from peak, pick level closest to volume-weighted mean (ties → cheaper). NO side uses `ask_ladder` (=no_dollars) directly — do NOT invert with 1-p. Float trap: round threshold to 3dp (`0.44-0.02=0.41999` excludes 0.42). Fallback = old 50% nudge. TTL unchanged: min(24h, 0.8×hours_to_expiry). Current trades untouched; applies to future orders only.
- In-play markets (live tennis etc.) = skip via 2h loop; micro-edge lost.
  **EXCEPTION (VJ 2026-08-03): VJ-flagged market + "want this" = trade intent. Follow his lead, place manually, bypass in-play/band/sub-50 gates. He placed Deckers 41c live when Mando skipped — lesson logged.
- Kalshi ticker = PMXT slug; Predexon search matches TITLES not tickers.
- Proposals expire 2h. Approve within a cycle.
- Cron: `predictor-scan` (2h, work hours, research+proposals), `predictor-fast-loop` (30m, $0, reconcile+arb+resolutions).

## Deep references

Full build/ops detail in absorbed skills: Kalshi API quirks, Polymarket gotchas,
PMXT Router arb, Predexon matching, two-tier cadence, mode semantics.
