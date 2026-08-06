# Prediction Market Alpha Playbook

A comprehensive reference for building trading bots on prediction markets — **Polymarket**, **Kalshi**, and cross-venue. This repository distills hard-won lessons from production bot operation: what edges work, what APIs are useful, what architectural patterns scale, and what antipatterns burn real capital.

## Who this is for

- **AI agents and engineers** bootstrapping prediction-market bots from scratch
- **Quantitative researchers** looking for validated edge ideas with honest evidence levels
- **Anyone** operating prediction-market systems who wants to avoid well-documented pitfalls

Everything here is written as **generic instructional content**. Treat it as a starting map, not a recipe — markets evolve, rules change, and what was alpha yesterday may be arbed out tomorrow.

## Contents

| File | Purpose |
|------|---------|
| [`PLAYBOOK.md`](./PLAYBOOK.md) | Step-by-step quickstart: from zero to first paper fire in a day |
| [`EDGES.md`](./EDGES.md) | ~20 categorised edge types with mechanisms, evidence levels, and implementation hints |
| [`APIS.md`](./APIS.md) | ~25 relevant APIs with auth, endpoints, rate limits, gotchas, and minimal working examples |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Battle-tested system design patterns — event loop, graduation pipeline, safety guards, observability |
| [`ANTIPATTERNS.md`](./ANTIPATTERNS.md) | ~20 failure modes that will burn you if you don't know to look for them |
| [`METHODOLOGY.md`](./METHODOLOGY.md) | How to systematically find, validate, and graduate strategies to live trading |
| [`NEG_RISK_NO_CARRY.md`](./NEG_RISK_NO_CARRY.md) | Deep-dive on one specific edge from `EDGES.md` §6b: structural NEG_RISK long-tail NO carry, hold-to-resolution |

## Quick orientation for AI agents

If you're an AI agent being asked to build or improve a prediction-market bot, ingest the files in this order:

1. **`ARCHITECTURE.md`** — understand the target shape of the system (event loop, paper/live bridge, graduation state machine, safety guards). Don't write code before you see the skeleton.
2. **`APIS.md`** — learn what data sources exist, what they cost, and what their documented-but-wrong-in-practice behaviors are (there are many).
3. **`EDGES.md`** — pick **one** edge to implement first. Favor low-complexity structural arbs (e.g., NEG_RISK sum arb, within-market YES+NO<1) over ML-style directional bets. For a fully-worked structural-carry deep-dive, see [`NEG_RISK_NO_CARRY.md`](./NEG_RISK_NO_CARRY.md) (paired with `EDGES.md` §6b).
4. **`ANTIPATTERNS.md`** — read this **before** writing any code. Many entries describe silent failure modes that corrupt paper evidence for weeks. Knowing the trap is 90% of avoiding it.
5. **`METHODOLOGY.md`** — run every strategy through the paper → shadow → live-canary → scale pipeline with Wilson lower-bound confidence. Never kill on aggregate WR before exhaustive cohort search.
6. **`PLAYBOOK.md`** — the concrete 10-step build sequence if you want opinionated scaffolding.

## Operating principles (TL;DR)

- **Data API > journal.** Any realized PnL derived from in-process journaling is lying to you. Reconcile every live trade against the exchange's on-chain or official activity feed. See `ANTIPATTERNS.md#journal-pnl-fiction`.
- **Exhaustive cohort search before killing.** Aggregate WR hides sub-cohort alpha. A strategy that looks like -20% ROI in aggregate often has a `price≥80¢` or `FADE` cohort at +60% ROI. See `METHODOLOGY.md#retarget-dont-amputate`.
- **Wilson lower bound, not point WR.** With small N, Wilson lb95 is the only honest confidence measure. 90% WR on N=5 is noise; 60% WR on N=100 is tradeable.
- **Paper-to-live graduation requires fresh out-of-sample data.** Historical cohort discovery is the hypothesis; fresh N≥30 post-deploy paper fires are the test. Don't confuse them.
- **Fees structurally bound every arb.** Kalshi's per-contract fee + Polymarket's taker fee set a minimum raw edge of ~400bps for cross-exchange arb to survive round-trip. See `APIS.md#kalshi-signed-api`.
- **Side/token alignment is the most common silent bug.** YES and NO outcome indices don't always map to `outcome[0]`/`outcome[1]` consistently across slugs. See `ANTIPATTERNS.md#side-token-alignment`.
- **Thin-book positions are capital-locked.** Small basket arbs <$200 recover 40-70% of mid on exit. Size like holds-to-resolution, not revolving capital.
- **Structural edges beat directional ones.** NEG_RISK mutual-exclusion (sum-arb in `EDGES.md` §1, hold-to-resolution NO carry in §6b / `NEG_RISK_NO_CARRY.md`) gives you guarantees the math enforces. Directional binary carry without basket diversification is variance-fade dressed up as alpha.

## What this repo is NOT

- Not a drop-in trading bot. It's a map.
- Not financial advice. Prediction markets have platform-specific regulatory status — check your jurisdiction.
- Not a guarantee any specific edge will work now. Evidence levels are documented; markets arb themselves out.
- Not a complete reference. Platforms evolve. Use this as a starting point, verify current state via official docs, then update your own playbook.

## License

MIT. Use, fork, extend, monetize — no attribution required but appreciated.

## Contributing

Pull requests welcome. If you've validated (or falsified) an edge listed here, open an issue with your methodology + evidence. The goal is an honest, evolving reference — not a marketing document.
