# predictor — AI-driven prediction market trading & research agent

Trading agent for **Polymarket** + **Kalshi** binary prediction markets.
Deterministic signal engine with optional LLM research overlay. Paper trading
by default (unrestricted thesis lab); live mode code-complete with all guardrails.

## Features

- **Dual venue**: Polymarket (gamma/CLOB/data APIs) and Kalshi (external-api,
  RSA-PSS signed auth, internal wallet — no gas needed)
- **Feature engine**: price, orderbook imbalance/depth, momentum, trade flow,
  time-to-expiry — every vector logged per decision
- **Calibrated probability blend**: market price (efficient baseline) + book
  + momentum + base rate + flow + optional LLM override (only counts when
  research supports ≥5c divergence)
- **Fee-aware EV**: Polymarket fee formula `rate × p × (1-p)` (bps), Kalshi
  zero-fee; slippage modeled per order style
- **Order lifecycle**: GTC limit orders → reconcile each scan (fill on limit
  cross, cancel after TTL) → resolution/manual close
- **Learning loop**: outcome tracking, calibration reliability table, Brier
  score, per-category bias
- **Cron-ready**: agent-driven scans with LLM research overlay, dual venue

## Mode semantics

| Mode | Purpose | Rules |
|---|---|---|
| `paper` (default) | Thesis validation | No caps, no approval, autonomous execution, Kelly-sized virtual $1000 |
| `live` | Real money | $2/trade cap, per-buy user approval, portfolio limits (daily loss, exposure, concurrency) |

**NO MARGIN TRADING EVER** — both modes, code-enforced (`MarginTradingError`).
**NO STOP-LOSS** — high-risk/high-reward events ride to resolution or manual close.

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

- **Kalshi**: fully wired (signed GTC orders, `bid`=YES / `ask`=NO, reduce_only
  closes, reconcile vs real exchange). Internal wallet — no external wallet/gas.
- **Polymarket**: requires wallet key + gas wiring (stub).
- Activation: `mode: live` + `venue: kalshi` in config. All live rules engage
  ($2/trade, approval per buy via `proposals`/`approve`/`reject`, portfolio limits).

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

- Polymarket live un-wired (needs wallet + gas)
- External sentiment feeds (LunarCrush) — pluggable, needs key
- Backtest replay harness — signals logged, replay not built
- Paper fills model is deterministic (no stochastic partial-fill simulation)

## Safety

- No margin ever (code-enforced)
- Live orders capped at $2 until you raise `risk.max_trade_usd`
- Every live buy requires explicit approval (2h expiry, EV re-check at execution)
- Fail-closed: approval re-check rejects if edge faded or book moved

## License

MIT
