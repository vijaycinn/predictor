# PMXT MCP + SDK — wiring, rate limits, field shapes (2026-08-03)

## Two different servers — don't confuse

- **Trading MCP**: `npx @pmxt/mcp` (npm pkg v2.54+). Real tools:
  fetchMarkets, fetchEvents, fetchOrderBook, fetchTrades, fetchOHLCV,
  getExecutionPrice, buildOrder, createOrder, submitOrder, cancelOrder,
  fetchBalance, fetchPositions, fetchOpenOrders, fetchMyTrades, loadMarkets
  (~38 total).
- **Docs MCP** (Mintlify auto-gen): server name "PMXT", tools
  search_pmxt / query_docs_filesystem_pmxt / submit_feedback, resource
  mintlify://skills/pmxt. ZERO trading value — it's a docs indexer. If a
  listing shows those tools, you connected the docs site, not the API.

## Hermes MCP env filtering — root cause of "PMXT API error: fetch failed"

Hermes FILTERS env for stdio MCP subprocesses: only PATH/HOME/USER/LANG/
LC_ALL/TERM/SHELL/TMPDIR + XDG_* pass through. API keys are excluded unless
explicitly listed in the `env` config key. A keyless pmxt server falls back
to LOCAL sidecar mode → tries localhost:3847 → sidecar not running →
`PMXT API error: fetch failed`.

- `hermes mcp add --env KEY=VALUE` writes the LITERAL secret into
  config.yaml — leak, avoid.
- Robust pattern: key in `~/.hermes/.env` + wrapper script; config points
  at the wrapper (no secret in config.yaml).
  `/data/.hermes/scripts/pmxt-mcp.sh`:
  ```bash
  #!/usr/bin/env bash
  set -a
  [ -f /data/.hermes/.env ] && . /data/.hermes/.env
  set +a
  export PMXT_API_KEY
  exec npx -y @pmxt/mcp
  ```
  config.yaml:
  ```yaml
  pmxt:
    command: /data/.hermes/scripts/pmxt-mcp.sh
    args: []
    enabled: true
  ```
- After config change: user runs `/reload-mcp`. Old MCP procs linger with
  stale (keyless) env — kill stale `npx @pmxt/mcp` procs before testing.
- Verify fix: wrapper-spawned proc environ contains `PMXT_API_KEY=pmxt_`.

## Rate limits (hosted api.pmxt.dev) — bursty per-IP throttle

- Works a few calls, then `HTTP 429 'Rate exceeded.'` — even on /health,
  even unauthenticated. Same request from a different egress (web_extract)
  returns `{"status":"ok"}` → API+key fine, the IP is throttled.
- SDK hides the 429: `JSONDecodeError: Expecting value: line 1 column 1`
  = plain-text 429 body, NOT a dead feed. Don't conclude "feed down".
- Pattern: batch scans in ONE python script; retry with backoff
  (sleep 8s × attempt, up to 4-6 tries) on 'Expecting value' / '429' /
  'Rate' / 'Unexpected token' in the error.
- Do NOT hammer the MCP tool in a loop: 3 consecutive failures → "MCP
  server 'pmxt' is unreachable", needs cooldown + /reload-mcp. Prefer SDK
  scripts for bulk scans, MCP for spot calls.

## Modes

- Hosted: `PMXT_API_KEY` set → api.pmxt.dev. Router (cross-venue clusters,
  arbitrage) REQUIRES hosted key.
- Local sidecar: no key → http://localhost:3847 (SDK spawns pmxt-core
  automatically; npm pkg `pmxt-core`, bins pmxt-server/pmxt-ensure-server;
  NOT on PyPI). Venue reads OK, Router ERR (cross-venue matching is
  hosted-only).
- Hybrid (docs-recommended): hosted Router for matching + local clients for
  venue writes. Kalshi writes = self-hosted only (hosted writes are
  Polymarket/Opinion/Limitless) — we keep the native Kalshi executor anyway.

## SDK field shapes

- `Router.fetch_markets(query=, limit=)` → UnifiedMarket: title/question/
  description, yes/no (outcome objects with `.price`), source_exchange,
  volume_24h, resolution_date, market_id, slug, url.
- Kalshi ticker lives in `m.slug` (e.g. KXEARNINGSMENTIONPLTR-26AUG03-REVE);
  `m.url` carries the Kalshi event ticker.
- `Router.fetch_order_book()` fails — Router requires exchange instances in
  RouterOptions. Use predictor's own `kalshi.fetch_orderbook(ticker)` for
  full ladders: returns best_bid/best_ask/bid_depth/ask_depth/bid_ladder/
  ask_ladder as [price, size] pairs.
- ArbitrageOpportunity fields: buy_price, buy_venue, sell_price, sell_venue,
  spread, confidence, relation; market_a/market_b = UnifiedMarket.
- `Router.fetch_arbitrage()` → list; sort by spread desc. Aug 2026 scan:
  18 opportunities, all 2028-election longshots (sub-50% probs, Myriad buy
  legs = discovery-only, no keys) → all SKIP per rules.

## Order creation — MCP createOrder 410s on Kalshi (hit live 2026-08-05)

`mcp__pmxt__createOrder(exchange=kalshi, ...)` → `PMXT API error: HTTP 410:
[410] Please switch to the V2 endpoints`. The pmxt MCP routes order creation
through the legacy V1 endpoint — NEVER use it for Kalshi orders. Same likely
for cancelOrder (V2 delete path). Workaround (verified live):
`python3 -c "from predictor import kalshi; kalshi.place_order(ticker, 'YES', count, price, hours_to_expiry=0, max_lifetime_hours=1.0)"`
from `/data/workspace/predictor` — V2 POST `/portfolio/events/orders` with
signed auth from env. This is the native executor anyway (see
`kalshi-v2-orders.md`); pmxt is read-only for Kalshi.

## Gotchas

- `pmxt.Kalshi()` constructor needs `pip install "pmxt[hosted]"`
  (eth-account). For reads, skip pmxt — use predictor's kalshi module.
- predictor `kalshi.discover_markets` caps ~40 / sports-first — won't find
  earnings-mention tickers. Find via pmxt Router search, then use slug +
  native fetch_orderbook.
- Public Kalshi endpoint api.elections.kalshi.com 400s on status param
  combos; predictor uses external-api.kalshi.com + auth_headers(method, path)
  (auth_headers needs 2 args).

## Search quirks — Kalshi via PMXT MCP (2026-08-04)

Same disease as native `/events?category=` (ignored): the MCP tools also
ignore/disappoint on Kalshi search:

- `fetchEvents(category="Fed")` → returns volume-sorted junk (golf,
  baseball, senate primaries — the Fed category filter is NOT applied).
  Don't trust the category param for discovery.
- `fetchMarkets(query="Fed decision September")` and
  `query="S&P 500 up down today"` → `[]` for REAL markets that exist.
  Free-text query misses Kalshi Fed/equity tickers. Do not conclude
  "market doesn't exist" from an empty result.
- **Reliable path: slug-direct lookup** — `fetchMarket(exchange=kalshi,
  slug=KXFEDDECISION-26SEP-H0)` etc. Works. Known slugs from RULES/NOTES:
  `KXFEDDECISION-26SEP-H0` (hold), `-C25` (cut 25bps), `-H25` (hike 25bps),
  `KXRATECUT-26DEC31` (any cut by Dec 31).
- **Sequential orderbooks throttle fast**: 3rd back-to-back
  `fetchOrderBook` on Kalshi → 429 (`Unexpected token 'R', "Rate exceeded."`).
  sleep ≥8s between calls recovers. For multi-book reads use
  `fetchOrderBooks(outcomeIds=[...])` batch variant when supported.
- Pattern for macro-batch follow-up: shortlist scan is sports-heavy (scan
  shortlist fills with tennis first); pull Fed/equity markets by known slug
  directly instead of trusting the shortlist to surface them.
