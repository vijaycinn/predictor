# METHODOLOGY — How to Find, Validate, and Graduate Strategies

This is the research-engineering playbook. Running strategies through this pipeline produces honest, tradeable alpha. Skipping steps produces confident garbage.

---

## The Graduation Ladder

Every strategy follows this path:

```
1. HYPOTHESIS     → define mechanism, expected edge, failure mode
2. PAPER          → implement, run 48-168h, collect ≥30 resolved trades
3. SHADOW-LIVE    → same signal fires paper record + LIVE at $1-2/trade
4. LIVE CANARY    → scaled to $5-25/trade, capped exposure
5. LIVE 1×        → full sizing at strategy's risk tolerance
6. LIVE 2× / 5×   → conditional scale-up on continued performance
7. KILL           → formal retirement with documented verdict
```

Each step has explicit, measured gates. Don't skip or fudge.

---

## Evidence Tiers (Wilson Lower Bound, Not Point WR)

**Never use point WR with small N.** Wilson lower bound (95%) is the honest confidence measure.

| N | Point WR | Wilson lb95 | Real confidence |
|---|----------|-------------|-----------------|
| 5 | 100% | 48% | Essentially random |
| 10 | 90% | 55% | Weak evidence |
| 30 | 80% | 62% | Decent signal |
| 100 | 70% | 60% | Strong signal |
| 1000 | 65% | 62% | Very strong |

Rule: quote Wilson lb95 in every strategy report. Point WR alone is a red flag.

---

## Data API as Ground Truth

**Rule**: Every PnL number that influences a decision (graduate, kill, scale) must be computed from exchange Data API, not from in-process journaling.

**Why**: Journal PnL has at least 4 documented ways to lie:
1. Exit-stamping on partial fills fabricates fake wins
2. Shared-DB ID collisions drop rows
3. Synthetic PnL formulas (fillRate × spread × rebate) bypass reality
4. Resolution-time oracle reads race against final settlement

**Reconciliation job** (daily minimum, hourly better):
```
for each resolved live trade:
  fetch trade from data_api.activity(user=proxy)
  update live_trades set
    actual_fill_price = ...,
    real_pnl = ...,
    exit_stamping_suspect = 0 if fully reconciled else 1
```

Downstream queries always filter `WHERE exit_stamping_suspect = 0`.

---

## Exhaustive Cohort Search Before Killing

When a strategy appears unprofitable in aggregate, **do NOT kill without exhaustive cohort search**. Aggregate hides sub-cohort alpha.

### The Search Procedure

```python
dimensions = [
  "asset",           # btc, eth, sol, ...
  "price_bucket",    # [0-5¢, 5-10¢, 10-20¢, 20-50¢, 50-80¢, 80-100¢]
  "elapsed_fraction", # [0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0]
  "side",            # YES, NO
  "utc_window",      # [us-open, us-close, asia, europe, off-hours]
  "day_of_week",     # mon-sun
  "prior_move",      # [down, flat, up]
  "realized_move",   # [down, flat, up]
  "post_entry_move", # [down, flat, up]
  "volatility",      # [low, med, high]
  "agreement",       # [bet-agrees-prior, bet-agrees-post, ...]
  "window_duration", # [1m, 5m, 1h]
  "size_bucket",     # [<$10, $10-50, $50+]
]

for cohort_size in [1-way, 2-way, 3-way]:
  for combo in combinations(dimensions, cohort_size):
    for variant in [NORM, FADE]:  # FADE inverts signal side
      rows = filter_live_trades_by(combo, variant)
      if rows.count < MIN_N_FOR_COHORT: continue
      metrics = {
        "n": rows.count,
        "wr": win_rate(rows),
        "wilson_lb95": wilson_lower_bound(rows),
        "mean_pnl": mean(rows.pnl),
        "total_pnl": sum(rows.pnl),
      }
      if metrics.wilson_lb95 >= 0.40 AND metrics.mean_pnl > 0:
        flag as RETARGET_CANDIDATE
```

At 74 dimensions × 1/2/3-way × 2 variants, you get ~6,000+ cohorts. Runs in minutes on SQLite.

### What to look for

- **FADE cohorts** (inverted signal side) — often reveal oracle-divergence patterns
- **Narrow price buckets** — high-entry NORM (`≥80¢`) is a classic clear-win cohort
- **Day/time patterns** — `dow=Wednesday` or `utc=us-close` can filter mechanical vs stochastic effects
- **Asset splits** — BTC may work where SOL doesn't

### Decision rules

If cohort search finds:
- ≥1 cohort at `N≥30, lb95≥55%, mean>0`: **retarget** as sub-gated v2 strategy
- ≥1 cohort at `N≥5, lb95≥40%, mean>0`: **paper-validate** the cohort before deciding
- Zero cohorts meeting above: formal kill, document verdict

**Observed**: 4 of 4 "killed" strategies tested via this methodology had hidden alpha. Killing on aggregate was systematically wrong.

---

## Retarget Don't Amputate

If cohort search finds a viable sub-cohort, **ship the sub-cohort as a new strategy**, don't revive the old one.

### Why fresh strategy name

1. Old strategy's graduation history is poisoned by pre-retarget losses
2. TRACKED_STRATEGIES config / auto-sizing history carries baggage
3. Measurement gets polluted by mixing pre-retarget and post-retarget fires
4. Operator clarity — seeing "directional (killed)" + "directional_v2 (shadow)" is cleaner than mystical revivals

### Naming convention

`{original}_{v2}_{sub_gate_descriptor}`:
- `directional_v2_norm80` (original `directional`, sub-gate `entry≥80¢ NORM`)
- `directional_v2_fade_sub80` (same strategy, different sub-gate)
- `crypto_updown_fade` (inverted variant)

Use `arb_class` tagging on fires for cohort isolation within the new strategy name.

---

## Paper-to-Live Divergence Expectation

**Budget 20-40% WR degradation between paper and live** for the same strategy.

Why paper overestimates live:
- Paper doesn't face slippage on thin-book fills
- Paper doesn't face adverse selection against market makers
- Paper doesn't lose capital to fees
- Paper-resolver bugs inflate low-entry strategies
- Paper uses mid, live uses ask-cross cost

Set graduation gates with this in mind:
- Paper WR 70% → expect live WR 50-60%
- Paper lb95 60% → expect live lb95 45-55%

If live severely underperforms paper (>40% WR degradation), suspect:
1. Silent paper-resolver bug (run paper-inflation audit)
2. Adverse selection (market makers identify your signal and front-run)
3. Category mismatch (paper universe ≠ live universe)

---

## Silent Data-Validity Fingerprints

Four diagnostic patterns indicate paper/live data is untrustworthy for graduation decisions:

### 1. Breakeven-% anomaly
Paper realizes `pnl = 0` on many rows. Means the resolver sees "no movement" and synthesizes zero PnL instead of real gain/loss. Run: `SELECT COUNT(*) FROM paper_trades WHERE pnl = 0 AND resolved = 1`.

### 2. Paper-live WR gap
If paper shows 70% WR and live shows 25% WR on same strategy, one of them is wrong. Compare by cohort, not aggregate.

### 3. Formula-shaped PnL
If PnL values cluster at specific multiples of a parameter (e.g., exactly 0.5% of size on every trade = rebate formula), your resolver isn't using real fills.

### 4. Journal sign/magnitude inflation
Journal realized PnL >> Data API realized PnL for same trades = stamping bugs. Quarterly audit: `compare journal_sum_pnl vs data_api_sum_pnl by strategy`.

If any ONE of these fires, paper data is uninformative for graduation until fixed.

---

## Live Canary Gate Discipline

Before promoting paper to live:

```
GATE 1 (enter shadow-live):
  resolved paper N ≥ 20
  inflation_flagged = 0
  Wilson lb95 WR ≥ 52%
  mean PnL/trade ≥ $0

GATE 2 (enter live canary at $2/fire × 3/day):
  resolved LIVE shadow fires N ≥ 15 (fresh post-deploy)
  Wilson lb95 WR ≥ 55%
  realized live PnL > $0
  no anomalous fill-price divergence vs paper

GATE 3 (scale to live_1x at full strategy sizing):
  resolved LIVE N ≥ 30 (since canary gate)
  Wilson lb95 WR ≥ 55%
  profit factor ≥ 1.2
```

**Fresh** means post-deploy, not historical in-sample. Historical exhaustive-search finds the hypothesis; fresh canary validates.

---

## Paper-Live Divergence Audit

Periodically (weekly or on strategy anomaly):

```sql
SELECT
  strategy,
  -- Paper
  (SELECT AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100 
   FROM paper_trades WHERE resolved=1 AND strategy=s.strategy) as paper_wr,
  (SELECT AVG(pnl) FROM paper_trades WHERE resolved=1 AND strategy=s.strategy) as paper_avg_pnl,
  -- Live
  (SELECT AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100 
   FROM live_trades WHERE resolved=1 AND exit_stamping_suspect=0 AND strategy=s.strategy) as live_wr,
  (SELECT AVG(pnl) FROM live_trades WHERE resolved=1 AND exit_stamping_suspect=0 AND strategy=s.strategy) as live_avg_pnl,
  -- Gap
  (paper_wr - live_wr) as wr_gap
FROM (SELECT DISTINCT strategy FROM paper_trades) s
ORDER BY wr_gap DESC
```

Gaps > 40pp flag the strategy for root-cause investigation.

---

## Tail Decomposition Before Graduation

Before ANY graduation decision, decompose the win distribution:

```
SELECT
  strategy,
  COUNT(*) as n,
  AVG(pnl) as mean_pnl,
  -- top 1% driver
  (SELECT SUM(pnl) FROM live_trades WHERE strategy=s.strategy AND exit_stamping_suspect=0 
   ORDER BY pnl DESC LIMIT (COUNT(*) / 100)) as top_1pct_total_pnl,
  -- rest
  (AVG(pnl) * COUNT(*)) - (top 1% total) as remaining_pnl
FROM live_trades s
WHERE exit_stamping_suspect=0
GROUP BY strategy
```

**Flag**: if top 1% of trades is >50% of total PnL, headline WR/PnL is single-row-driven. Could be legitimate fat-tail OR artifact (e.g., oracle-read race generating one huge fake win).

**Rule**: always verify ≥1 row of the top tail via manual end-to-end audit (market page, on-chain settlement, Data API) before graduation. If you can't verify it, it's not real.

---

## Post-Kill Verification Pattern

After formally killing a strategy (or removing live flag):

1. **Verify VPS picked up**: `ssh vps "grep 'strategy_name' config.ts"` shows `false`
2. **Verify scan cycle reflects**: next scan-cycle-end log shows 0 fires for that strategy
3. **Watch for 24h**: no new `strategy=killed_name` rows in live_trades
4. **Monitor remaining open positions**: existing positions continue to resolve; no new ones opened

Skip step 1, miss that CI didn't deploy, find out 7 commits later the strategy was still firing in production.

---

## The Meta-Pattern: PM Oracle Divergence

Across multiple strategies, one unifying principle emerges:

> **Prediction market oracles systematically diverge from scanner reference data.**

Manifestations:
- Crypto: scanner uses Binance tick, market resolves on TWAP/Coinbase/UMA (~93% divergence)
- Weather: scanner uses forecast consensus, market resolves on specific weather-station feed
- Sports: scanner uses live feed, market resolves on UMA/league-official (rare divergence)
- Macro: scanner uses FRED, market resolves on specific release (usually aligned but with edge cases)

**Rule**: Every scanner should declare which oracle the resolved market uses. If the oracle differs from the reference data, test FADE variant in exhaustive search.

---

## Research Output Discipline

Every retargeting research pass produces:

1. **Exhaustive-search verdict doc**: `docs/research/{strategy}-exhaustive-search-{date}.md`
   - Top-20 cohorts by score (Wilson lb95 × √N)
   - Best NORM and best FADE for each dimension
   - Full per-trade ledger in companion `.json`

2. **Retarget spec** (if viable cohort found): `docs/research/{strategy}-v2-retarget-spec-{date}.md`
   - Sub-gate definitions + entry-price-range + side
   - Expected fire cadence
   - Graduation gate per sub-cohort
   - Implementer handoff notes

3. **Formal kill entry** (if no viable cohort): added to `FORMALLY_KILLED_STRATEGIES` constant + memory file documenting the verdict

4. **Foundational memory** (if a meta-pattern surfaces): `memory/feedback_{pattern}.md` encoding the learning as a rule for future sessions

Memory entries save weeks of re-discovery. Invest in writing them.

---

## Confidence-Scoring Framework (for Directional Strategies)

For strategies that produce "buy X with probability P" recommendations:

```typescript
interface Signal {
  source: string        // "weather-consensus", "whale-flow", "orderflow-copy"
  edge: number          // (model_prob - market_prob), signed
  confidence: number    // 0.0-1.0, from source-specific calibration
  direction: "YES" | "NO"
}

// Sigmoid to cap edge→conf relationship
confidence = sigmoid(edge / edgeScaleForSource) * maxConfForSource

// Multi-signal aggregation: conservative, not multiplicative
aggregatedConfidence = max(signals, by: confidence) * agreementBonus
where agreementBonus = 1.0 if 1 signal, 1.1 if 2 agreeing, 1.25 if 3+ agreeing
```

Rules:
- Cap any single source's confidence at 0.85 (nothing is truly certain)
- Disagreeing signals floor confidence at 0.50 (when sources conflict, treat as coin-flip)
- Never combine signals that share underlying data (e.g., two weather models from same parent forecast) — false agreement

---

## Strategy Re-Evaluation Cadence

- **Daily**: scan-cycle metrics (PnL, fire count, rejection reasons by strategy)
- **Weekly**: paper-live divergence audit, tail decomposition for active strategies
- **Monthly**: exhaustive cohort re-search for any strategy that added ≥50 new resolved rows
- **Quarterly**: systemic audit — compare portfolio-level return on total deployed capital; verify graduated strategies still deserve their tier

---

## Anti-Patterns in Research Methodology

- **In-sample cohort discovery** = hypothesis, NOT confirmation. Always validate fresh out-of-sample.
- **Single-row tail drivers** inflate WR/PnL. Decompose before trusting aggregate.
- **Category-biased "100% WR"** is almost always category-bias. Stratify by category.
- **Small-N fat-tail kills**. 10% WR on 5 trades is NOT evidence of failure if mean PnL is positive and distribution is fat-tailed.
- **Aggregate kills hide sub-cohorts**. 4/4 tested strategies had hidden alpha. Exhaustive search first.

---

## Closing Rule

**Before you kill any strategy**, ask: 

1. Have I run exhaustive cohort search?
2. Have I verified the top-tail rows are real via Data API?
3. Have I checked paper-live WR gap?
4. Have I tested FADE variant?
5. Have I examined if the resolution oracle differs from my scanner reference?

If answers are not all yes, you're killing prematurely. Don't.
