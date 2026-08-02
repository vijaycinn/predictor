# predictor — AI-driven prediction market trading & research agent

Trading agent for **Kalshi** (live) + **Polymarket** (reference) binary
prediction markets. Deterministic signal engine with research overlay.
Live trading on Kalshi with a full guardrail stack. **Mission: maximize
MARGIN OF PROFIT** — win rate is vanity, profit is the job (VJ 2026-08-02).

## Features

- **Venue**: Kalshi live (external-api v2, RSA-PSS signed auth, internal
  wallet — no gas needed). Polymarket as independent probability source
  (gamma API, `outcomePrices` authoritative — CLOB books degenerate).
- **Feature engine**: price, orderbook imbalance/depth, momentum, trade flow,
  time-to-expiry — every vector logged per decision
- **Calibrated probability blend**: market price + book + momentum + base
  rate + flow + optional LLM override
- **Fee-aware EV**: slippage modeled per order style; Kalshi zero-fee
- **Order lifecycle**: GTC/IOC limit orders → reconcile each scan → resolution
- **Learning loop**: outcome tracking, calibration, Karpathy-style
  metric-vs-decision analysis (weekly review)
- **Cron-ready**: live-flip scanner (30m), geo-trades scan (7pm CT),
  weekly order review (Sun 1am CT), all agent-driven

## Hard rules (authoritative: `RULES.md` — file wins over code)

1. **LIMIT ORDERS ONLY** — no market orders, ever (hard assert in code)
2. **Buy band: YES only 0–40c** (`max_buy_price_cents: 40`); NO side exempt
3. **Never pay >10% above approved price** (`max_price_raise_pct: 10`),
   guard reference = user-approved price in sig, never the live book
4. **VOLUME-PEAK maker pricing** — follow the money: rest at the level where
   volume concentrates (density mode), NOT the highest fillable level.
   Thin top-of-book bids are market-maker bait.
5. **Order TTL: DEFAULT 1 HOUR** unless VJ explicitly overrides; never exceed
   24h; leave ≥20% of event time
6. **$1/trade cap**, no margin (code assert), no stop-loss — ride to resolution
7. **NEVER bet if outcome probability < 50%** — every bet, prob from an
   INDEPENDENT source (Polymarket cross-venue or verifiable research),
   never Kalshi's own book alone
8. **Live tennis TTL aligned to score state** — set-1-early 30-60m,
   mid-match 15-30m, moved >10c from limit = cancel. Format-aware:
   men GS best-of-5, men non-GS best-of-3, women best-of-3
9-14. Crypto only ≤1mo expiry; price ≠ edge; report blockers; consolidated
   pre-flight gate (`risk.pre_flight_check` — all rules, no path skips)
15-16. Suggestion suppression (sub-50% never offered); fail-closed guards
17. **Geo updates from DeItaone feed** (`x.com/DeItaone`, xurl)
18. **Geo-trades window: 7pm CST only** — choke-points (Hormuz/Suez) →
   oil/gold/VIX risk-off; de-escalation inverse; esp. Sunday PM sets week tone
19. **Weekly order review Sun 1am CT** — evaluate MARGIN OF PROFIT;
   Karpathy-style report (state→analyze→hypothesize→fix);
   **implementation changes ONLY on VJ approval**

**Mission: MARGIN OF PROFIT is the ONLY success metric.** Sole purpose is
maximizing profits. Every rule serves the margin.

## Mode semantics

| Mode | Purpose | Rules |
|---|---|---|
| `paper` (default) | Thesis validation | No caps, no approval, autonomous execution, Kelly-sized virtual $1000 |
| `live` | Real money | $1/trade cap, band ≤40c, win floor ≥50%, pre-flight gate, per-buy user approval |

**NO MARGIN TRADING EVER** — both modes, code-enforced (`MarginTradingError`).
**NO STOP-LOSS** — high-risk/high-reward events ride to resolution or manual close.
**LIMIT ORDERS ONLY** — no market orders, ever (hard assert in `place_order`).

## Install

```bash
pip install -r requirements.txt
cp config.yaml config.local.yaml   # adjust venue/gates/risk as needed
```

## Usage

```bash
python3 cli.py scan                          # full cycle, paper (autonomous)
python3 cli.py scan --venue kalshi           # Kalshi pool
python3 cli.py scan --llm-overrides ov.json  # apply researched LLM estimates
python3 cli.py status                        # positions + P&L
python3 cli.py orders                        # order lifecycle view
python3 cli.py close <trade_id>              # manual exit (live: reduce_only sell)
python3 cli.py cancel <trade_id>             # cancel resting order
python3 cli.py calibrate                     # reliability table, Brier, category bias
python3 cli.py resolve                       # settle closed markets
python3 scripts/live_flip_scan.py            # live flip-zone candidates (cron 30m)
python3 scripts/geo_scan.py                  # DeItaone geo read -> Kalshi shortlist (cron 7pm CT)
python3 scripts/search_market.py "query"     # Kalshi name/ticker search (full pagination)
python3 scripts/weekly_review.py             # weekly order review -> margin of profit (cron Sun 1am CT)
```

LLM override file: `{"<condition_id>": 0.12, ...}`. For Kalshi, condition_id is
the market ticker (`KX...`); for Polymarket it's the `0x` condition id.

## Credentials (env)

| Var | Venue | Purpose |
|---|---|---|
| `KALSHI_API_KEY` | Kalshi | API key ID (Account & security → API Keys) |
| `KALSHI_PRIVATE_KEY` | Kalshi | RSA PEM (downloaded `.key` content) |
| `POLYMARKET_PRIVATE_KEY` | Polymarket | Live wallet (not yet wired — needs gas) |

Public market data works keyless on both venues. Credentials only unlock live
trading/portfolio reads.

## Live trading

- **Kalshi**: fully wired (signed GTC/IOC limit orders, `bid`=YES / `ask`=NO,
  reduce_only closes via IOC, reconcile vs real exchange). Internal wallet —
  no external wallet/gas.
- **Polymarket**: reference only (probability cross-venue check). Live wiring
  requires wallet key + gas (stub).
- Activation: `mode: live` + `venue: kalshi` in config. All live rules engage
  ($1/trade cap, band ≤40c, win floor ≥50%, approval via `proposals`/`approve`/`reject`).
- Exits: `reduce_only` sells require IOC (`time_in_force: immediate_or_cancel`)
  and must omit `expiration_time` — Kalshi rejects reduce_only+GTC
  (`reduce_only can only be used with IoC orders`, hit live 2026-08-02).

## Research tooling

- **investor-agent MCP** — local MCP server (Yahoo Finance): quotes, options,
  market movers, earnings calendar, fear/greed, technical indicators. Runs
  from source at `/data/workspace/investor-agent` (`node dist/index.js`),
  wired into Hermes as `mcp_servers.investor-agent` (npm package NOT
  published — the README's `npx investor-agent` is stale).
- **DeItaone feed** — geopolitical/macro source of truth via xurl
  (`x.com/DeItaone`). Drives the 7pm CT geo-trades scan.
- **Predexon MCP** — market-data tools (Polymarket, Kalshi data-only).

## Architecture

```
discover (per-category, volume-gated)
  -> ingest (orderbook, price history, trades, OI)
  -> features (price/orderbook/sentiment/time vectors)
  -> signal (calibrated prob blend + confidence tier + fee-aware EV)
  -> filters -> Kelly sizing -> [proposal gate (live)] -> executor
  -> SQLite (markets, snapshots, features, signals, proposals, trades, outcomes)
  -> learn (resolution, calibration, bias) -> reconcile (order lifecycle)
```

- `predictor/ingest.py` — Polymarket public APIs
- `predictor/kalshi.py` — Kalshi data + signed auth + order ops
- `predictor/features.py` — feature vectors (documented in DB)
- `predictor/signals.py` — probability blend, confidence, EV math
- `predictor/risk.py` — filters, Kelly sizing, hard limits (live)
- `predictor/executor.py` — paper/live executors, order lifecycle reconcile
- `predictor/scanner.py` — scan orchestration + approval-gated execution
- `predictor/learn.py` — resolution, calibration, performance

## Predexon layer (primary market-data tool)

- Predexon MCP server wired into Hermes (`mcp_servers.predexon`, npx
  predexon-mcp, `PREDEXON_API_KEY` env). Tools surface as `mcp_predexon_*`
  after restart. 40 tools: Polymarket market data + smart-wallet analytics,
  Kalshi markets/trades/orderbooks, Binance, Limitless, Opinion, Predict.Fun.
- Kalshi via Predexon = **data only** (their docs: no Kalshi trade execution).
  Live Kalshi orders stay on the native Kalshi path in `executor.py`.
- **Predexon has NO `find_matching_markets` tool** (verified against
  predexon-mcp 0.3.0 source + REST openapi). Cross-venue matching is built in
  `predictor/arb.py` with strict equivalence gates: Jaccard token-set
  similarity (0.85+ strong), disqualifier-token rejection (vice/senate/house…),
  close-time proximity, numeric-target overlap, Kalshi candidate subtitles.
- CLI: `python3 cli.py arb --check` — Kalshi vs Polymarket synthetic-arb scan;
  `--health` pings Predexon. Dry-run only; weak matches never surfaced.

## Known limitations

- Polymarket live un-wired (reference only — needs wallet + gas)
- Backtest replay harness — signals logged, replay not built
- Paper fills model is deterministic (no stochastic partial-fill simulation)

## Safety

- No margin ever (code-enforced)
- LIMIT ORDERS ONLY (hard assert in `place_order`)
- Live orders capped at $1 (`risk.max_trade_usd`); YES band 0-40c;
  never >10% above approved price; win floor ≥50% (independent source)
- Every live buy requires explicit approval (pre-flight gate re-checks
  all rules at execution: limit-only → win floor → band → raise → no-margin)
- Fail-closed: approval re-check rejects if edge faded or book moved
- Suggestion suppression: sub-50% outcomes never offered as options

## Scripts & docs

- `scripts/live_flip_scan.py` — live-option flip candidates (mid 0.35-0.65,
  tight spread, volume-gated). Outputs pick-list table with side/limit/TTL;
  `[B]` = buyable ≤40c (Ribero pattern: fair ≥50% while cheap side ≤40c).
  Cron every 30m, waking hours 7am-10pm CT only.
- `scripts/geo_scan.py` — DeItaone feed → geo sentiment → Kalshi oil/gold
  shortlist. Choke-point escalation = risk-off; de-escalation = risk-on.
  Time-gated: silent outside 7-8pm CT (rule 18).
- `scripts/search_market.py` — full-pagination name/ticker search.
  Fixes two bugs: 10-hit cap that hid Tolev/Cazacu, and wrong event-prefix
  filter that excluded the `KXATPCHALLENGERMATCH` family.
- `scripts/weekly_review.py` — weekly order review, MARGIN OF PROFIT metric,
  mechanical-vs-thesis failure split. Cron Sun 1am CT (rule 19).
- `RULES.md` — authoritative hard rules (file wins over code)
- `NOTES.md` — macro/election context, Fed path, case studies (Ribero win)

## Case studies

- **Ribero win (+$1.20)** — bought 2 @ 0.40 when fair ~0.56 (up a set 6-4,
  down a break 1-4 in Bo3). Lesson: band gate checks LIMIT price, not fair
  value — 56c of probability bought at 40c = 16c edge. VJ's call beat SKIP.
- **Cazacu lesson** — live order TTL must track score movement, not fixed 1h.
  Price moved 0.61→0.82 while a 0.40 order sat unfillable; stale limit =
  dead weight. Rule 8.
- **Donski incident** — underdog approved at list price 0.34, book repriced
  in-play to 0.93, filled at 0.90. Fresh book used as reference; no band/raise
  guards. Fixed: approved-price-in-sig discipline + price-raise guard.
- **Tennis underdog batch** — 8 sub-40c picks placed without research, all
  sub-50% outcomes, most resolved worthless. Price filter ≠ edge. Fixed:
  win floor ≥50% + suggestion suppression.

## License

MIT
