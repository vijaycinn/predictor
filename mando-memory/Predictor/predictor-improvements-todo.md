---
tags: [predictor, todo, arb, polymarket, improvements]
date_created: 2026-08-16
status: active
last_updated: 2026-08-16
---

# Predictor Improvements — TODO (actionable)

Source: Oracle Boar tweet (2026-08-01, Polymarket arb playbook, grounded in
IMDEA/Oxford study https://arxiv.org/pdf/2508.03474, $40M/yr realized arb).
Analysis by Mando 2026-08-16. Durable action list — do not treat as done
until each item is verified live.

## Why this matters

Predictor arb = cross-venue ONLY today (PMXT fetch_arbitrage + Predexon
matching), sell-only Kalshi (rule 10). Tweet describes 2 arb games the
predictor does NOT run:
- Rebalancing arb (intra-market): sum of YES prices ≠ $1 → risk-free basket.
- Combinatorial arb (cross-market): related markets drift against logic.

Both missing → both are new edge classes.

## P1 — build now

- [ ] **P1a. Intra-market sum-to-1 scanner (`cli.py sumarb`)**
  - Iterate every Kalshi multi-outcome market; sum YES prices.
  - `|sum − 1| ≥ 3c` → flag basket (Kalshi $0 fee → tight threshold OK).
  - Pure arithmetic, no LLM, no cross-venue. Drop-in beside existing `arb` commands.
- [ ] **P1b. Exhaustive-coverage guard** (blocks phantom arb)
  - Multi-outcome markets hide "Other"/"No winner" outcomes. Missing outcome = fake gap.
  - Verify exhaustive + mutually exclusive BEFORE summing. Check market metadata for all listed outcomes.

## P2 — extend

- [ ] **P2a. Combinatorial scan**
  - Extend PMXT pairs to intra-venue nested markets: winner↔margin, threshold ladders same asset+date.
  - Reuse Predexon Jaccard matcher as candidate-pair generator + close-time/topic filter (paper's two-stage filter).
  - Break condition: narrow outcome priced ≥ broad outcome that contains it → bundle pays.
- [ ] **P2b. Arb sizing carve-out**
  - $1 cap / 40c band / 50% win floor = directional rules. Risk-free basket ≠ directional bet.
  - Propose `risk.max_arb_usd` separate sizing + explicit VJ approval. POLICY CHANGE — VJ decides.

## P3 — hygiene

- [ ] **P3a. Non-atomicity on baskets**
  - Already have limit-only + wall gate + "abort if leg can't fill". Apply to baskets: matched TTL, all-or-nothing across legs.
- [ ] **P3b. Tag arb P&L separately**
  - Weekly review (margin-of-profit) mixes directional + arb. Add `source=arb` tag so Karpathy metric-vs-decision shows which engine earns.
- [ ] **P3c. RULES.md clarification**
  - Rule 10 "NO BUY-SIDE CAPTURE" risks misread: basket arb buys ALL outcomes at once = risk-free, not directional buy-side. Add one clarifying line.

## Caveats (keep visible)

- $40M was Polymarket (UMA oracle). Kalshi resolution cleaner (CFTC-regulated).
- PM.us freeze (rule 9c) still blocks richest PM volume — PM.com stays truth-only.
- Arb gaps on Kalshi may be thin; size for partial fills + slippage (paper: arb is non-atomic).

## Cross-refs

- [[Kalshi/learnings]]
- [[rules]]
- Source tweet: https://x.com/i/status/2083525491093286989
