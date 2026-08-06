# EDGES — Validated and Hypothesised Alpha Sources

This document catalogues edge categories observed in prediction markets. Each entry describes the **mechanism** (why it theoretically works), the **implementation shape**, and an **evidence tier** reflecting real-world observation.

## Evidence tiers

- **S** — Structural arb, guaranteed profit if executed correctly (fees/slippage permitting)
- **A** — Strong empirical edge validated on N≥100 with Wilson lb95 ≥ 55%
- **B** — Promising on N=30-100, needs out-of-sample confirmation
- **C** — Hypothesis only, worth paper-testing
- **F** — Tested and failed, documented for posterity

---

## 1. NEG_RISK Bracket Sum-Arb (Tier S)

**Mechanism**: Polymarket's NEG_RISK (mutually-exclusive) markets should have YES-side prices summing to ≤ 1.0 + fees. When a 10-bucket event (e.g., "How many rate cuts in 2026?") has outcome YES prices summing to 1.03, buying all NO legs or equivalently shorting the synthetic basket locks in 3pp edge minus fees.

**Shape**:
- Universe: all negRisk events with ≥ 3 outcomes
- Fire condition: `sum(ask_yes_i) > 1.0 + fee_threshold` AND all legs have visible asks at acceptable depth
- Capital: proportional across legs to equalize payout

**Gotcha — F#14 partial-basket invalidation**: if ONE leg has `ask=null` (no sellers), you cannot construct the basket. Scanner MUST verify every leg is fillable before firing. Sum>1.03 with one dead leg is a trap.

**Evidence**: Observed across political/macro/commodity baskets. Market is generally efficient — 42 events scanned returning 0 arbs is typical. Cadence low but when they hit, clean execution.

---

## 2. Within-Market Arb (YES + NO < 1.0) (Tier S)

**Mechanism**: On a binary market, `ask_yes + ask_no < 1.0` means you can buy both outcomes, guaranteed to redeem for $1.00 at resolution → risk-free spread.

**Shape**:
- Poll top-500 markets by volume
- `ask_yes + ask_no <= 0.98` (ideally tighter to survive round-trip fees)

**Gotcha**: Usually closes within seconds of creation. Requires fast scan + fast fire. Don't bet on finding these at low cadence.

**Evidence**: Top-10 closest typically at sum=1.001 (10bps gap). Real opportunities are rare, need high-frequency scanning.

---

## 3. Cross-Exchange Arbitrage (Tier A — but fee-gated)

**Mechanism**: Same real-world event listed on Polymarket AND Kalshi at different implied probabilities. Buy cheaper side on venue A, sell expensive side on venue B, collect spread.

**Shape**:
- Maintain pair-mapping (Polymarket slug ↔ Kalshi ticker) for mirror events
- Fire when implied-prob delta > minimum net edge threshold

**Gotcha — Kalshi fee structural floor**: Kalshi charges `0.07 × p × (1-p)` per contract. At p=0.50 that's ~1.75% per side. Polymarket adds ~2% × min(p, 1-p) × size. Round-trip at mid-prices is ~450bps. **Any raw edge under ~400bps is net-negative.** Sub-200bps raw edges ALWAYS lose after fees.

**Seed pair strategy**: prefer extreme-p pairs (p=0.05 or p=0.95) where Kalshi's fee drops quadratically to ~0.33%/contract. At extremes you can profit from smaller raw edges.

**Evidence**: Rare but real during catalyst events (Fed decisions, election nights, breaking news). Routine cadence is zero.

---

## 4. Cross-Market Monotonicity Violations (Tier A)

**Mechanism**: On Kalshi ladder markets (e.g., "Fed rate > X.XX%"), `P(rate > 3.75)` must be ≥ `P(rate > 4.00)` by definition. When market prices violate this monotonicity, there's an intra-ladder arb.

**Shape**:
- For every ladder pair `(Lower_strike, Upper_strike)`, check if `ask_yes(Lower) < ask_yes(Upper)`
- If violated: Buy Lower YES + Buy Upper NO → one of the three regions always pays >1.0

**Gotcha — NO ask computation**: To buy NO you pay `1 - yes_BID`, not `1 - yes_ask`. Using `1 - yes_ask` underestimates cost by the full spread width. This has fabricated false-positive arbs multiple times.

**Evidence**: Real but thin depth. Most monotonicity violations have <$50 cap at quoted prices and 5-7pp spreads that further erode edge.

---

## 5. Sum-Arb Lock-In (Tier A)

**Mechanism**: For clustered mutually-exclusive outcomes (e.g., "Who wins party primary" with 8 candidates), buying NO on all 8 at sum > 1.025 guarantees $1 payout minus fees for up to 7 losing outcomes.

**Shape**:
- Watch named-outcome baskets (parties, states, candidates)
- Lock-in trigger at sum ≥ 1.025 (conservative; 1.03+ is even cleaner)
- Fire paired executions across all legs simultaneously

**Execution discipline**: 
- Pre-compute leg sizes to equalize payout
- Use GTC orders to avoid market-order slippage
- Cancel partial fills if > N% unfilled after T seconds

**Evidence**: Single best edge observed in practice. When election cycles heat up, multiple baskets hit 1.025-1.030 simultaneously. Can generate significant capital deployment in a single wave.

---

## 6. Clear-Win Convergence (Tier B)

**Mechanism**: Markets with already-decided outcomes (final score is in, ballot count is done) sometimes remain priced at 90-95¢ instead of 99¢ due to slow market makers. Buying YES at 92¢ when the outcome is effectively 100% is pure convergence alpha.

**Shape**:
- Resolution-window scanner: markets with end_date in last 0-24h
- Reference-fact verification (sports: BALLDONTLIE box score; weather: reported temperature; crypto: spot price at resolution)
- Fire only if `reference = outcome` with near-zero uncertainty AND market price < 0.97

**Category trap — commodities/macro**: oil price "above $X" markets can keep oscillating even after the "reference time" because UMA oracle uses specific feeds that may diverge from spot. Sports/weather are cleaner categories for this edge.

**Evidence**: Works in sports and weather categories. Failed badly on commodity/macro markets due to oracle-feed divergence.

---

## 7. Tail-Fade / Premium Harvest (Tier B)

**Mechanism**: Low-probability binary outcomes (hurricanes landfalling in pre-season, specific earthquakes, tail election outcomes) are often priced at 5-10¢ for variance-premium reasons, even when base rates are ≤2%. Selling NO (or buying the expensive side) captures the premium.

**Shape**:
- Universe: low-prob tails with empirical base rate available
- Fire when `market_implied_prob > empirical_base_rate × 2`
- Size small (1-2% bankroll per tail) — fat-tail by nature

**Cycling pattern**: after a fill, the ask tends to refill over 2hr initial + 5-120min steady-state on thin-book Kalshi markets. Poll book state for re-fire eligibility; don't clock-estimate.

**Evidence**: Consistent small-$ edge. Resolution-window holding discipline matters — 40-70% of mid recovered on early exit due to thin-book.

---

## 8. Sports Resolution Sniping (Tier B)

**Mechanism**: Final score hits the feed 2-15 seconds before prediction market repricing. A WebSocket-connected bot can read the score, verify outcome, and fire limit orders at mid before market makers update.

**Shape**:
- Polymarket Sports WebSocket (`wss://sports-api.polymarket.com/ws`) streams `home_score`/`away_score`/`status`
- BALLDONTLIE API as cross-check (NBA/NFL/MLB/NHL/EPL)
- Fire when `status == "final"` and market price < 0.90 for winning side

**Canonical slug gotcha**: Polymarket slugs are `{sport}-{away}-{home}-{date}`. `outcomes[0]` is the AWAY team YES probability. Use `prices[1]` for home YES, swap tokenIds accordingly. Getting this wrong silently fires wrong-side bets.

**Evidence**: Works during active seasons. NFL/NBA playoffs are the highest-volume windows.

---

## 9. Weather Bucket Arb (Tier C)

**Mechanism**: Weather markets bucketed by temperature range can be priced inconsistently across adjacent buckets. If `P(60-65°F)` seems systematically overpriced and `P(55-60°F)` underpriced given forecast, conditional arb exists.

**Shape**:
- Consensus-model forecast (OpenWeatherMap + Open-Meteo + MeteoBlue majority vote)
- Per-city calibration (market's local tendency to over/under-price specific buckets)
- Fire NO on buckets where consensus says < market-implied prob

**Observed pitfall — directional gate inversion**: high-entry-price NO bets (≥85¢) often lose in live despite looking safe in paper — adverse selection. Counter-intuitively, the profitable cohort is `entry < 80¢` with scanner-side FADED.

**Evidence**: Paper data looked strong, live performance divergent for subsets. The `≥80¢ NORM` sub-cohort is cleaner than the full universe.

---

## 10. Insider Cluster Detection (Tier B)

**Mechanism**: Large one-sided trades by multiple wallets converging on a specific market within a short window often indicates information asymmetry (injury news, match-fix, breaking political intel). Copying the aggregate flow with tight risk controls captures the signal.

**Shape**:
- Query wallet activity via Polymarket Data API (`/activity?user=`)
- Filter to wallets with `profit_factor ≥ 2.0`, `maxDrawdown < 25%`, `numTrades ≥ 100` (elite traders)
- Detect convergence: ≥ 2 Tier-S/A wallets, ≥ $10K net buy, same direction, same market, within 60-min window
- Copy direction with strict size cap ($5-$25/fire)

**Taxonomy — sports cluster vs news herd**:
- **Sports clusters**: 5-13 wallets, 3-8× ROI, mechanical information (injury/fight/match-fix). TRADE THIS.
- **News herds**: 25-40 wallets on losing narrative bets (e.g., breaking political events). DON'T TRADE — these are retail reacting to headlines, not insiders.
- Filter: `HERD_THRESHOLD = 25 wallets` at (market, side). Above threshold = herd, ignore.

**Convergence-arb false positive**: fresh-wallet single-event scorers fire equally on directional insiders AND basket arbers (who open many markets simultaneously). Sibling-market lookup (same wallet, ±48h end_ts, different market_id) discriminates.

**Evidence**: Sports cohort has real edge. News herd cohort is negative-EV. Methodology-heavy — wallet-shape signals must be properly designed.

---

## 11. Whale Following (Tier B)

**Mechanism**: Top traders by profit factor on Polymarket have demonstrable alpha. Mirroring their buys (scaled down, with risk bounds) captures a fraction of their edge.

**Shape**:
- Profile top-500 traders from Beefy P&L subgraph weekly
- Score: `profitFactor × (1 - maxDrawdownPct) × log10(numTrades) / 3`
- Tiers: S (pf≥3.0, 200+ positions, DD<10%), A (pf≥2.0, 100+ pos), B (pf≥1.5, 50+ pos)
- Copy Tier-S trades within 60s of observation, size = 0.5% of their trade size

**Evidence**: The Graph subgraph has `profitFactor`, `maxDrawdown`, `winRate` per trader. Elite whales exist (pf > 4.0 over 800+ positions). Copying works as a weak signal — boost to other strategies rather than standalone.

---

## 12. Crypto Up/Down Fade / Oracle Divergence (Tier B)

**Mechanism**: 5-minute crypto "will BTC be above $X at T" markets resolve via a specific oracle feed (TWAP, Coinbase, UMA-weighted) that **systematically diverges** from spot (Binance tick). A scanner betting with the scanner-implied direction loses ~93% of the time. Inverting (FADE) captures the divergence.

**Shape**:
- Scanner observes Binance spot vs market price for 5-min updown markets
- FADE: if scanner says "will resolve UP", fire NO; if scanner says DOWN, fire YES
- Entry window: `elapsed_fraction ∈ [0.40, 0.80]`
- Size: $1-$5/fire (cheap tokens, 100-300× payouts when right)

**Evidence**: On historical N=28 data, NORM direction was 2W/26L (7% WR), FADE was 26W/2L (93% WR, Wilson lb95=77.4%). Mechanism plausibly causal — different oracle feed. Requires out-of-sample confirmation before live flip.

**Related pattern**: any scanner whose target-oracle differs from its reference-price source has a FADE candidate. Check before killing.

---

## 13. Directional Gate Inversion (Tier B)

**Mechanism**: "High-edge" directional signals (e.g., "market implies 40% but our model says 80%") often lose in live because the "big edges" are where the model is wrong, not where the market is wrong. Counter-intuitively, **small edges with high fill prices** can be the winning cohort.

**Shape**:
- For weather/directional strategies: `entry ≥ 80¢ NORM` often wins (8W/0L observed) while `entry < 80¢` loses
- For crypto: `entry ≤ 5¢` with FADE wins (high-variance fat-tail)
- Stratify by entry price bucket before trusting any aggregate WR

**Anti-pattern**: aggregate 11% WR directional strategy was killed, but exhaustive cohort search found `entry ≥ 80¢ NORM` sub-cohort at 100% WR on N=8 and `entry < 80¢ FADE × dow=Wednesday` at +$245 on N=24. Killing on aggregate hid the alpha.

**Evidence**: See METHODOLOGY.md exhaustive-cohort-search pattern.

---

## 14. Threshold-to-Bracket Matching (Tier C)

**Mechanism**: Kalshi's threshold markets ("rate > 3.75%") and Polymarket's NEG_RISK brackets ("rate bucket = 3.50-3.75") describe the same underlying distribution. If the Kalshi implied cumulative distribution is inconsistent with the Polymarket bucket distribution, cross-venue arb exists.

**Shape**:
- Parse both ladder structures into a common CDF representation
- Compare `P(X ≤ threshold)` between venues
- Fire when venues disagree by > 400bps after fees

**Complexity**: medium-high. Needs per-event canonical-pair detection, threshold-to-bucket matching logic, and cross-venue execution coordination.

**Evidence**: Hypothesised, not yet deployed. Attractive because Kalshi's thin-book threshold markets frequently misprice vs Polymarket's deeper bracket books.

---

## 15. Temporal Anchoring (Tier C / Failed)

**Mechanism**: Consecutive-month macro markets (CPI-June vs CPI-July, monthly Fed dot plots) should exhibit decorrelation because each month is an independent draw from the conditional-on-policy distribution. If market prices show strong serial correlation (anchoring to last month's outcome), arb exists.

**Shape**:
- Pull consecutive-month CPI/PCE/PPI ladders
- Compare implied probability of each bucket across months
- Flag gaps > 15pp as anchoring suspects

**Evidence**: Tested, null result. Market makers handle month-to-month coupling correctly. Apparent "gaps" were artifacts of one month being near-resolved ($1.00 certainty) vs others (0.55-0.85 uncertainty).

---

## 16. Hurricane / Weather Pre-Season (Tier B)

**Mechanism**: Markets like "Will a Cat 3+ hurricane make US landfall by May 31?" are priced for variance premium (5-10¢ even when base rate <2% during pre-season). Fading the YES (= selling or buying NO) captures the premium.

**Shape**:
- Pre-season scanner flags all active hurricane/tropical-storm markets
- Fire NO at 5-10¢ prices when meteorological conditions don't support YES resolution
- Hold to resolution (time-decay works in your favor)

**Evidence**: Part of general tail-fade pattern. Works when expected, but pre-season Kalshi markets can have wide spreads — check thin-book exit cost before committing >$200.

---

## 17. USGS Earthquake Markets (Tier C)

**Mechanism**: Markets conditional on specific seismic events (M6.5+ in California in 2026, etc.) can be priced based on rolling-window base rates. USGS provides the reference feed for resolution.

**Shape**:
- Monitor active EQ markets
- Check USGS M5+ feed for events that shift resolution probability
- Fire immediately on qualifying events if market hasn't repriced

**Evidence**: Edge-case, low cadence. Worth a scanner if you already have the infrastructure but not a primary alpha source.

---

## 18. UMA Dispute Arbitrage (F — Failed)

**Mechanism**: UMA oracle disputes create temporary mispricing windows where disputed markets trade at unrealistic discounts. Betting on the eventual "correct" resolution captures edge if dispute is wrongly called.

**Evidence**: Killed. Commodity/macro markets violate convergence thesis — UMA disputes often are legitimate disagreements about ambiguous resolution criteria, not clean mispricings. 100% WR on non-commodity markets dropped to ~40% WR once category-unfiltered. Category-biased backtests lie.

**Lesson**: any "100% WR" strategy on small N is almost certainly category-biased. Always stratify by market category before trusting.

---

## 19. FRED Macro Anchors (Tier C)

**Mechanism**: Federal Reserve Economic Data provides authoritative macro series (unemployment, CPI, GDP). Markets tied to these series have explicit resolution sources — whenever FRED publishes a new print, markets should reprice instantly. Latency captures edge.

**Shape**:
- FRED API polls for new releases on publication schedule
- Cross-reference with Polymarket/Kalshi markets indexed to the series
- Fire on markets that haven't repriced within seconds of release

**Evidence**: FRED publishes on schedule, so you can pre-position near publication time. Works as a cron-triggered strategy rather than continuous scanning.

---

## 20. Orderflow / Large-Fill Copy (Tier C)

**Mechanism**: Large single-block fills on Polymarket (e.g., $20K+ notional in one trade) often indicate informed flow. Copying the direction briefly (60-300s window) captures the post-fill drift.

**Shape**:
- Subscribe to Polymarket CLOB WebSocket (`wss://ws-subscriptions-clob.polymarket.com/ws/market`)
- Parse `last_trade_price` events, identify fills > $20K notional
- Require ≥ 3 large fills in 5-min window AND market 1-48h from resolution
- Copy direction with small size

**Evidence**: Promising paper signal. Needs careful filtering to avoid copying the late-tape retail rushes ("news herd" problem).

---

## General edge-hunting principles

1. **Structural arbs first**. Sum violations, monotonicity, within-market are guaranteed profit when they appear. No model needed.
2. **Cross-venue requires fee floor awareness**. Platform fees structurally bound minimum edge. Check before coding.
3. **Oracle-divergence is a category, not a strategy**. Every scanner using a reference feed should check whether the resolution-oracle matches.
4. **Cohort-stratify before killing**. Aggregate WR hides sub-cohort alpha. 74-dim exhaustive search is 20 minutes of runtime; it's cheaper than months of mis-killed strategies.
5. **Thin-book exits are capital locks**. Before firing any position you can't revert, compute worst-case exit cost.
6. **Paper-live divergence is normal**. Budget 20-40% WR degradation between paper and live for the same strategy. Plan sizing accordingly.

---

See `METHODOLOGY.md` for how to validate these edges systematically, and `ANTIPATTERNS.md` for the silent failure modes that invalidate naive measurements.
