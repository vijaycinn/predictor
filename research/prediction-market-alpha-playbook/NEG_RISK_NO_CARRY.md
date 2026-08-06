# NEG_RISK Long-Tail NO Carry

**Edge type**: Structural hold-to-resolution carry on neg-risk (mutually-exclusive) baskets.
**Tier**: B — slow but high-probability; cadence-bound, not contested.
**Generic instructional content** — no specific bankroll, fee, or implementation numbers.

---

## Thesis in one paragraph

In a NEG_RISK event with N candidates and one winner, exactly N−1 outcomes resolve NO. This is **structural mutual exclusion**, not a probabilistic claim. Long-tail candidates whose YES is priced ≤ ~3¢ (i.e., NO ≥ ~97¢) are pricing themselves as "almost certainly losing." Buying NO on each long-tail and holding to resolution converts that ~3¢/share spread into a near-deterministic carry. The basket can only fail if a candidate the market priced as a long-tail actually wins — and by construction at least N−1 long-tails always win NO.

This is not a directional bet on which candidate wins. It is the observation that "exactly one wins" is a structural fact of neg-risk markets.

---

## Why it works

- **NEG_RISK guarantees the math**: Polymarket's NEG_RISK flag means the underlying contract architecture enforces "exactly one of N resolves YES." There is no "all lose" or "two win" outcome.
- **Long-tail NOs are the part of the basket the market has already concluded.** The front-runner's NO trades near 0.50 and is excluded by the price floor; what's left is a basket of consensus losers.
- **Payout is deterministic on resolution**: each NO that resolves NO redeems for $1. Profit per leg = $1 − entry − fees. Variance per leg is bounded; basket-level variance comes only from the pathological case where a "long-tail" wasn't actually a long-tail.

The economic profile is closer to "selling out-of-the-money insurance against dead-on-arrival candidates" than "predicting an event."

---

## When it applies

A market is eligible for NO-carry if all of:

1. **Event-level**: marked NEG_RISK by the venue (e.g., Polymarket's `enableNegRisk` / `negRiskAugmented`) — NOT inferred from sibling structure.
2. **Sibling-set thickness**: ≥ 5 sibling markets in the event. Below this, basket diversification is too weak to absorb the rare tail-winner.
3. **Σ(YES) sanity check**: sum of YES prices across siblings ≈ 1.0 (within a tolerance band, e.g. 0.95–1.10). This is the structural fingerprint of a clean mutual-exclusion basket. Deviation indicates either a malformed event or a non-NEG_RISK shape that happens to look similar.
4. **NO price floor**: NO ≥ ~0.97 (= YES ≤ ~0.03) on the candidate leg. The exact floor is a strategy parameter — too low and you fire on consensus contenders, too high and your fire rate collapses.
5. **Resolution window cap**: hold time bounded (e.g., resolve within 7 days). Capital lock is the main opportunity cost; the further out the resolution, the worse the APR even if the WR is 100%.
6. **Basket diversification cap**: per-event position cap (e.g., 5 long-tail legs max) to bound exposure when a tail unexpectedly wins.

---

## Default-deny categories

- **Sports exact-score / spread**: variance-fade trap. Looks like a long tail, can flip in a single play. Mutual exclusion still holds, but per-leg variance is far above the "consensus loser" baseline assumed by the strategy.
- **Distributional bin events** (e.g., "GDP growth: <2%, 2–3%, 3–4%, >4%"): mutual exclusion holds, but the "candidates" are bins of a single underlying number, not independent actors. Behavior is dominated by the distribution mode, not by the strategic dynamics that make political long-tails reliably losers. Detect via title regex on range-bound language.
- **Single-actor markets**: any market without sibling structure (the basket *is* the diversification — without ≥5 siblings the strategy degenerates into directional binary YES carry, which has known variance-fade failure modes).

---

## Exit rule

**Hold to resolution. No mid-trade stop loss.**

A long-tail NO drifting from 0.99 to 0.85 means the market has re-priced *another* tail as the new front-runner — your position can still resolve NO and pay $1. A stop would systematically realize losses on positions that go on to recover. The thesis is mutual exclusion, not price stability; price action between entry and resolution is noise.

The rare full-loss (a tail actually wins) is accepted as a cost of doing business and is what the per-event diversification cap exists to absorb.

---

## Sizing intuition

- **Flat per-fire** (e.g., a fixed % of bankroll per leg). Kelly tiers add complexity without changing the structural argument; the WR is so high that variance from wrong-sizing dominates variance from optimal-sizing.
- **Per-event basket cap** is the real risk control. A single basket can have N−1 winning NOs; if N−1 ≥ basket_cap, a tail-winner only kills `basket_cap` legs out of `basket_cap`, not `basket_cap` out of `(N−1)`. The cap protects you from overcorrelating into one event.
- **Concurrent cap** caps total exposure across all open events.

---

## What can go wrong

1. **A long-tail actually wins.** Priced at NO=0.99, redeems at $0. Loss per leg is roughly the full entry. Mitigation: per-event cap + entry floor.
2. **Categorical contracts vs N independent binaries.** Both shapes are mutual-exclusive. Redemption mechanics differ slightly (one `redeemPositions(conditionId, indexSets)` call vs N per-token redemptions), but the strategy math is identical. Detect via the venue's NEG_RISK flag, not by counting condition IDs.
3. **Capital lock.** A 7-day position is 7 days of opportunity cost. Cascade resolution-window passes (T-3d → T-5d → T-7d) so the scanner prefers faster-resolving baskets when both exist.
4. **Resolution disputes** (UMA on Polymarket): rare but can delay settlement 24–72h beyond expected end-date. Affects APR more than win-rate.

---

## What this is NOT

- **Not a directional view** on any candidate. If you find yourself reasoning about "is X likely to win," you have left the strategy.
- **Not a sum-arb.** The NEG_RISK sum-arb (Tier S in `EDGES.md` §1) closes a present-tense pricing inconsistency for risk-free profit. NO-carry takes a position and waits — it's a hold-to-resolution edge, not a now-vs-now edge.
- **Not a binary-market strategy.** Predecessor strategies that bought YES at ≥0.975 on *any* binary (cross-arb residue, soccer exact-scores, etc.) lost money on variance-fade and contested hype markets. NO-carry only fires on neg-risk *baskets* — the basket is the diversification.

---

## Summary

| Aspect | Property |
|---|---|
| Edge source | Structural mutual exclusion of NEG_RISK markets |
| Holding period | Hold to resolution (typically 3–7 days) |
| Variance | Bounded by per-event basket cap; basket-level WR very high |
| Cadence | Slow — gated by neg-risk events approaching their resolution window |
| Sensitivity to fees | Low (fees on NO at extremes are a small fraction of the edge) |
| Sensitivity to slippage | Moderate (fire-time book re-check matters; orderbook is thin at the long-tail extreme) |
| Capacity | Limited by depth at NO ≥ floor on each leg, summed across concurrent events |
| Failure mode | A market-classified long-tail actually wins → full per-leg loss; bound exposure with the per-event cap |
