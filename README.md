# predictor — AI-driven prediction market trading & research agent

Polymarket (venue: binary markets) trading agent. Deterministic signal engine +
optional LLM overlay. Paper trading by default; live path stubbed.

## Architecture

```
discover (gamma /events, per-category) -> ingest (CLOB book, price history, data API trades/OI)
  -> features (price/orderbook/sentiment/time vectors)
  -> signal (calibrated prob blend + confidence + fee-aware EV)
  -> filters -> Kelly sizing -> risk limits -> paper/live executor
  -> SQLite (markets, snapshots, features, signals, trades, outcomes, blocked)
  -> learn (resolution tracking, calibration report, bias by category)
```

- `predictor/ingest.py` — Polymarket public APIs (read-only, no auth)
- `predictor/features.py` — feature vector construction (documented in DB)
- `predictor/signals.py` — probability blend, confidence tiers, EV math
- `predictor/risk.py` — mechanical filters, Kelly sizing, exposure limits
- `predictor/executor.py` — PaperExecutor (deterministic fills), LiveExecutor stub
- `predictor/learn.py` — outcome resolution, calibration/Brier, category bias
- `predictor/scanner.py` — one full scan cycle
- `cli.py` — scan | status | calibrate | resolve

## Probability blend

```
P(YES) = w_market*price + w_book*book_adj + w_momentum*momentum_adj
       + w_base*base_rate + w_sentiment*flow_adj + [w_llm*llm_override]
```

Market price stays dominant (efficient baseline). LLM weight only activates when
an override exists (`--llm-overrides`); otherwise redistributed to market price.
All component values logged per signal for transparency/backtest.

## EV math (per share)

```
EV_raw = P(side) - price(side)
fees:   Polymarket formula  fee = shares x feeRate x p x (1-p), feeRate in bps
        (gamma fields makerBaseFee/takerBaseFee are bps; 1000 = 10%)
        fallback: config fees.*_per_share when market has no fee schedule
slippage: maker=0 (rest at limit), taker=half_spread x aggressiveness
EV_net = EV_raw - fee - slippage
Gate:   EV_net >= ev_min_net (0.02) AND |edge| >= min_edge (0.03)
```

## Venues

- `venue: polymarket` (default) — gamma/CLOB/data APIs, token-id based
- `venue: kalshi` — `external-api.kalshi.com`, ticker-based, prices in dollars
  (0.74 = 74%). Orderbook returns yes/no bids only; asks derived (yes bid X =
  no ask 1-X). MVE combo markets excluded via `mve_filter=exclude`.
- Kalshi scan gates live under `kalshi.scan` (volumes ~10x smaller than Polymarket)
- Override per run: `python3 cli.py scan --venue kalshi`

### Kalshi credentials (env)

| Var | Value |
|-----|-------|
| `KALSHI_API_KEY` | API key ID (UUID) from Kalshi → Account & security → API Keys |
| `KALSHI_PRIVATE_KEY` | RSA private key PEM (downloaded `.key` file content) |

Auth = RSA-PSS/SHA256 over `timestamp + METHOD + path` (no query), sent as
`KALSHI-ACCESS-KEY` / `KALSHI-ACCESS-SIGNATURE` / `KALSHI-ACCESS-TIMESTAMP`.
Public market data works keyless; credentials unlock portfolio/orders (live path).
`python3 cli.py scan --venue kalshi` prints auth readiness to stderr.

## Mode semantics

- **paper (default)** — unrestricted thesis lab. No $2 cap, no approval gate,
  no portfolio hard limits. Trades execute autonomously on Kelly-sized virtual
  capital ($1000). Purpose: validate hypotheses, gather calibration data.
- **live** — all rules bite: `max_trade_usd` ($2), per-buy approval, portfolio
  limits (daily loss, exposure, concurrency). Not wired for execution yet.
- **NO MARGIN TRADING EVER applies in both modes** — code raises
  `MarginTradingError` if the flag is ever set true (scanner + executor double
  guard). Only fully cash-collateralized binary event contracts.

### Live approval flow (not active until mode: live)

```bash
python3 cli.py proposals        # list pending
python3 cli.py approve 1 2      # approve + execute (re-verifies EV first)
python3 cli.py reject 3         # reject
```
Proposals expire after `approval.ttl_hours` (2h). `recheck_on_approve` re-fetches
the book and recomputes EV at execution time — fails closed if edge faded.

## Order lifecycle

Every buy becomes a GTC limit order (maker-preferred):

```
BUY -> RESTING (limit not crossed) | OPEN (crossed)
  RESTING -> reconcile pass each scan:
      market comes to limit  -> FILLED (OPEN, fill at limit/better)
      order_ttl_hours (4h)   -> CANCELED
  OPEN -> closed at resolution (auto P&L) or `cli.py close <trade_id>`
```

- `python3 cli.py orders` — lifecycle view (resting/open, req/fill sizes, exchange order id)
- `python3 cli.py close <trade_id>` — manual exit: paper closes at book,
  live Kalshi places reduce_only sell
- `python3 cli.py cancel <trade_id>` — cancel resting (live: cancels on exchange too)
- Live mode reconciles against Kalshi's real order book each scan (GET
  /portfolio/orders, fills, positions)

**NO STOP-LOSS** (per VJ): prediction markets are high-risk/high-reward events;
positions ride to resolution or manual close. `execution.stop_loss: false`.

## Live trading (Kalshi wired, not active)

- `mode: live` + `venue: kalshi` — real GTC orders via signed API, $2/trade cap
  + approval gate + portfolio limits all active. Kalshi wallet is internal
  (no external wallet/gas needed); balance $61.61.
- Polymarket live still requires POLYMARKET_PRIVATE_KEY + gas wallet (stub).
- Order placement is code-complete but NOT fired — requires explicit go.

## Usage

```bash
python3 cli.py scan                          # full cycle, no LLM overlay
python3 cli.py scan --shortlist /tmp/sl.json # emit LLM review candidates
python3 cli.py scan --llm-overrides /tmp/ov.json  # apply researched estimates
python3 cli.py status                        # positions + P&L
python3 cli.py calibrate                     # reliability table, Brier, category bias
python3 cli.py resolve                       # settle closed markets
```

Override file shape: `{"<condition_id>": 0.12, ...}`.

## Cron (agent-driven loop)

Hermes cron job runs every 2h (CT work hours):
1. `scan --shortlist` — get candidate markets with real liquidity
2. Agent researches top candidates (web), forms independent P(YES) per market
3. Writes overrides JSON only where evidence supports >= 5c divergence
4. `scan --llm-overrides` — trades fire on fee-aware EV
5. Deliver brief: top ideas, paper positions, risk state

See cron job "predictor-scan" for the live prompt.

## Live trading (NOT enabled)

- `mode: live` in config.yaml + `POLYMARKET_PRIVATE_KEY` env
- LiveExecutor stub — requires py-clob-client wiring (EIP-712 orders)
- Do NOT enable until paper track record validates calibration

## Learning loop

- Every scan: resolution check settles closed markets, marks trade P&L
- `calibrate` — decile reliability table + Brier score + per-category bias
- Signals store prob_yes, confidence, EV, features at decision time for backtest
- Parameter changes: propose in config, never silent

## Known limitations

- Paper fills: RESTING maker orders never re-checked for later fills
- No order cancellation/exit management yet (lifecycle hooks TODO)
- Sentiment = market-internal proxies (flow, imbalance, momentum); external
  social feeds (LunarCrush) pluggable later
- LLM overlay runs in cron agent loop, not inside the package
