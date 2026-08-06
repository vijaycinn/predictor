# APIS — Data Sources and Execution Venues

Every API entry documents: **purpose**, **auth**, **endpoints**, **rate limits**, **cost**, and **known gotchas from production use**. Verify current behavior against official docs — APIs drift.

---

## Polymarket

### CLOB Trading API
- **Purpose**: Order placement, cancellation, fills on Polymarket's Central Limit Order Book
- **Base**: `https://clob.polymarket.com`
- **Auth**: L1 (API key) + L2 (HMAC-signed) derived from proxy wallet private key via the official SDK
- **SDK**: `@polymarket/clob-client` (npm)
- **Gotchas**:
  - **`POLYMARKET_ADDRESS` must be the PROXY wallet (0x...)**, not the EOA. EOA fails ownership checks silently on order placement.
  - Microshare balance mismatch: on-chain balance `52966100` microshares cannot satisfy an order for `52.97` shares (which rounds up to `52970000` microshares). Floor sizes to 4 decimals: `Math.floor(size * 10000) / 10000`.
  - Signature type: default to `POLY_PROXY`. Override via env if the account needs EOA or POLY_GNOSIS_SAFE signature.
  - `sellPosition()` with partial fills: CLOB may report `status: "matched"` while the caller's timeout-polling logic interprets as "not sold". Trust the response, not your poll loop — "matched" means shares transferred.

### Data API (Activity + Positions)
- **Purpose**: Historical trades, current positions, PnL. **This is the ground truth for live PnL.** Never trust in-process journaling alone.
- **Base**: `https://data-api.polymarket.com`
- **Auth**: None required
- **Key endpoints**:
  - `/positions?user=<proxy_addr>&sizeThreshold=0.1&limit=500` — open positions
  - `/activity?user=<proxy_addr>&type=TRADE&limit=100` — historical trades (reaches back further than token-based queries)
- **Gotchas**:
  - Position `curPrice=0` + `redeemable=true` means the position **lost**, not "locked win". Always check `curPrice` before reporting PnL.
  - `redeemable: false` is a LIVE position (not yet resolved). Don't interpret as "lost".
  - Use `/activity?user=W` for historical replay on resolved markets — token-based queries miss resolved-market trades.
  - Address is case-sensitive in some scenarios. Use lowercase consistently.

### Gamma API (Markets Metadata)
- **Purpose**: Market discovery, metadata, slug lookup
- **Base**: `https://gamma-api.polymarket.com`
- **Auth**: None
- **Key endpoints**:
  - `/markets?slug=<canonical-slug>` — fetch a specific market
  - `/markets?negRisk=true&active=true&limit=500` — NEG_RISK universe for bracket arbs
  - `/events?limit=500&order=volume24hr&ascending=false` — top-volume events
- **Gotchas**:
  - **`_q=` free-text search is broken** — returns garbage (often "GTA VI" catch-all) regardless of query. Always use canonical slug construction, never free-text search.
  - `clobTokenIds` field is a JSON string containing an array of 2 token IDs (YES + NO). Parse: `JSON.parse(m.clobTokenIds) as string[]`.
  - Slug format: `{category}-{descriptor}-{date}`. Sports slug is `{sport}-{away}-{home}-{date}` — first outcome is AWAY team.

### Polymarket CLOB WebSocket
- **Purpose**: Real-time trade events, orderbook updates
- **URL**: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- **Subscribe**: `{ auth: {...}, markets: [tokenId], type: "market" }` with `custom_feature_enabled: true` for enhanced events
- **Events**: `last_trade_price`, `best_bid_ask`, `market_resolved`
- **Reliability**: Reconnect logic required — disconnects every 1-5 minutes are common. Backoff + resubscribe pattern.

### Polymarket Sports WebSocket
- **URL**: `wss://sports-api.polymarket.com/ws`
- **Auth**: None
- **Stream**: All active games with `home_score`, `away_score`, `status`
- **Use case**: Final-score sniping (fire as soon as `status == "final"` on mispriced markets)

### The Graph (Beefy P&L Subgraph)
- **Purpose**: Top-trader discovery, wallet profitability metrics
- **Endpoint**: via The Graph decentralized network (requires API key)
- **Schema fields**: `profitFactor`, `maxDrawdown`, `winRate`, `numTrades`, per-wallet
- **Gotchas**:
  - **Free tier trips "payment required" errors under production load.** Allocate budget or mirror data locally.
  - `maxDrawdown` is returned as raw USDC / 1e6 (not percentage). Convert accordingly.
  - Some queries return `S=0, A=0` aggregate scores — symptom of over-normalization, not empty data. Verify field semantics before trusting.

---

## Kalshi

### Signed API (Trading + Market Data)
- **Purpose**: Order placement + market data on CFTC-regulated event contracts
- **Base**: `https://trading-api.kalshi.com/trade-api/v2`
- **Auth**: RSA-PSS signed requests using PKCS8 private key file + `KALSHI-ACCESS-KEY` header
- **Key endpoints**:
  - `GET /markets/{ticker}/orderbook` — depth
  - `POST /portfolio/orders` — place order
  - `GET /portfolio/positions` — current positions
  - `GET /markets?event_ticker=<X>&status=open` — market discovery
- **Gotchas**:
  - **Response uses `orderbook_fp` (not `orderbook`)** with `yes_dollars` / `no_dollars` arrays, each entry `[priceString, sizeString]` — both strings, both require `parseFloat`. Prices are DOLLAR values ("0.0100" = 1¢), NOT integer cents.
  - **Fee formula**: `fee = 0.07 × p × (1-p) × contracts`. At p=0.50 that's 1.75%/contract. Drops quadratically to 0.33%/contract at p=0.05.
  - Any cross-exchange arb needs **≥400bps raw edge** to survive round-trip fees. Sub-200bps raw edges are ALWAYS net-negative. Don't lower this floor.
  - `fill_count_fp` field returns `*_fp` float-strings not raw counts. `parseFloat` required. Relying on raw counts on first live fire can leave a position naked for minutes before detection.
  - **Close-time vs expected-expiration**: sports tickers pad `close_time` by 2+ years for cancellation flexibility. Use `expected_expiration_time` as the programmatic anchor for when resolution happens.
  - Side derivation via `outcome.toLowerCase() === "yes"` breaks on non-Yes/No markets (Up/Down, team names, parties). Use `outcomeIndex` instead.

### Kalshi Fee Economics (reference)
- Per-contract fee: `0.07 × p × (1-p)`
- Round-trip at mid (p=0.5): ~3.5%
- Round-trip at extremes (p=0.05 or 0.95): ~0.66%
- **Implication**: Extreme-p pairs are the only structurally-profitable seed universe for cross-exchange arb without huge edges.

---

## Dome API (Prediction Market Aggregator)

- **Package**: `@dome-api/sdk` (npm)
- **Purpose**: Cross-platform market data, wallet PnL, matching-market discovery
- **Auth**: API key from `docs.domeapi.io`
- **Key methods**:
  - `getWalletPnl(address)` — consolidated cross-venue PnL
  - `getMatchingMarkets(query)` — find mirror markets across venues
  - `getCandlesticks(market, timeframe)` — OHLC for any prediction market
- **When to use**: Aggregation across Polymarket + Kalshi without maintaining custom mapping tables. Good for discovery, weaker for low-latency execution (use venue-native APIs for fire paths).

---

## Crypto Price Feeds

### Binance WebSocket (Primary — Free, Unlimited)
- **URL**: `wss://stream.binance.com:9443/ws/<symbol>@miniTicker`
- **Multi-symbol**: stream several with `/` separator: `btcusdt@miniTicker/ethusdt@miniTicker/solusdt@miniTicker`
- **Auth**: None
- **Rate**: Unlimited
- **Gotcha**: **Blocked in US** (HTTP 451). Requires VPN for US-based operators.

### Binance REST Klines (Historical)
- **Endpoint**: `GET /api/v3/klines?symbol=<X>&interval=1m&limit=<N>`
- **Auth**: None
- **Rate**: 1200 req/min
- **Use case**: Historical reference-price lookup for strategies that need "price at time T"
- **Supported symbols**: BTC, ETH, SOL, XRP, DOGE, BNB, and most major USDT pairs. **HYPE is NOT supported**.

### CoinGecko (Historical Fallback — WITH WARNINGS)
- **Base**: `https://api.coingecko.com/api/v3`
- **Auth**: Demo key (free, rate-limited) or Pro (paid, higher limits)
- **Rate**: Demo key trips 429 rate-limit aggressively under production load (every few seconds)
- **Critical gotcha**: **If your scanner short-circuits to CoinGecko on every call, 429s silently kill the strategy.** Use Binance klines as primary for BTC/ETH/SOL/XRP/DOGE/BNB; only fall through to CoinGecko for unsupported symbols (HYPE). Validate fallback logic — a `needsCoinGecko(symbol)` helper that returns true for everything routes ALL traffic to the rate-limited endpoint.

### CoinStats (Alternative)
- **Base**: `https://openapiv1.coinstatsapp.com`
- **Auth**: API key
- **Rate**: Much more generous than CoinGecko at paid tier
- **Native**: 5-minute OHLC bars (matches crypto-updown market window exactly, no kline aggregation needed)
- **Use case**: Good backup or primary for crypto reference prices

---

## Weather Data

### OpenWeatherMap
- **Base**: `https://api.openweathermap.org/data/2.5`
- **Endpoints**: `/weather?q={city}`, `/onecall?lat={}&lon={}&exclude=minutely,hourly`
- **Auth**: API key (free tier: 60 req/min, 1M/month)
- **Use case**: Primary weather source for bucket-arb strategies

### Open-Meteo (Free, Unlimited)
- **Base**: `https://api.open-meteo.com/v1`
- **Auth**: None
- **Rate**: Unlimited
- **Use case**: Secondary consensus source. Free tier has no hard limits.

### MeteoBlue
- **Base**: `https://my.meteoblue.com`
- **Auth**: API key (paid)
- **Use case**: Third consensus source. Combining three independent models (OpenWeatherMap + Open-Meteo + MeteoBlue) for majority-vote forecasts is more robust than any single source.

---

## Sports Data

### The Odds API
- **Base**: `https://api.the-odds-api.com/v4`
- **Auth**: API key
- **Endpoints**: `/sports/{sport}/odds`, `/sports/{sport}/scores`
- **Rate**: Depends on plan (free tier: 500 requests/month)
- **Use case**: Pre-tipoff moneylines, over/under lines for sports market pricing

### BALLDONTLIE
- **Base**: `https://api.balldontlie.io/v1`
- **Auth**: API key (free tier available)
- **Sports**: NBA, NFL, MLB, NHL, EPL
- **Use case**: Box scores for resolution verification, live scores for in-game signals, player stats for prop-bet resolution

### OwlInsight
- **Purpose**: Aggregated sports signals (betting line movements, sharp money detection)
- **Auth**: API key
- **Use case**: Secondary signal for sports markets — not load-bearing, boost-quality

### Polymarket Sports WebSocket (re-reference)
- See Polymarket section above — often the lowest-latency source for live game state on markets you're already trading.

---

## Macro & News

### FRED (Federal Reserve Economic Data)
- **Base**: `https://api.stlouisfed.org/fred`
- **Auth**: API key (free)
- **Endpoints**: `/series?series_id=<X>`, `/series/observations?series_id=<X>`
- **Key series**: UNRATE (unemployment), CPIAUCSL (CPI), GDP, FEDFUNDS
- **Use case**: Authoritative source for macro market resolution

### LunarCrush
- **Purpose**: Crypto social sentiment, trending tokens
- **Auth**: API key
- **Use case**: Weak signal for crypto directional trades. Not primary alpha.

### Finlight
- **Purpose**: News catalyst stream
- **Auth**: API key (`sk_...`)
- **Use case**: Pre-event positioning on breaking-news markets. Latency-sensitive — WebSocket preferred.

### Brave Search
- **Base**: `https://api.search.brave.com/res/v1`
- **Auth**: API key (`BSA-...`)
- **Use case**: Ad-hoc market discovery, real-world fact verification. Less load-bearing than specialized APIs.

---

## Seismic & Environmental

### USGS Earthquake Feed
- **URL**: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`
- **Auth**: None
- **Rate**: Free, cached 1-min TTL
- **Use case**: Resolution reference for earthquake prediction markets (CA M6.5+, etc.)

---

## Infrastructure

### Polygon RPC (Alchemy / Infura / QuickNode)
- **Use**: Required for Polymarket CLOB order signing + redemption execution
- **Critical**: **Public RPCs fail in production.** Polygon public endpoints (polygon-rpc.com, ankr, publicnode) return `noNetwork` errors and silently drop events on ethers v5 `contract.on()`. Use a paid RPC from Alchemy, Infura, or QuickNode.
- **Env**: `POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/<key>`

### UMA Oracle (On-Chain)
- **Purpose**: Resolution authority for disputed Polymarket markets
- **Contract**: Look up current UMA oracle on Polygon
- **Use case**: Monitor disputes, watch for resolution events on tracked markets

### Telegram Bot API
- **Base**: `https://api.telegram.org/bot<TOKEN>`
- **Auth**: Bot token from @BotFather
- **Use case**: Notifications (fills, errors, daily PnL), monitoring. Essential for operating without constant dashboard watching.

---

## Model Context Protocol (MCP) Servers

If you're building an AI-agent-assisted bot, these MCP servers dramatically accelerate development:

### Polymarket Subgraph MCP
- Exposes The Graph subgraphs as agent-queryable tools
- Tools: `get_top_traders`, `get_account_pnl`, `get_market_positions`, `get_orderbook_trades`, `search_markets_enriched`
- Great for whale discovery + market research from within an AI session

### Brave Search MCP
- Exposes Brave Search (web/news/image) as agent tools
- Use for real-world fact verification during agent-driven research

### Context7 MCP
- Live documentation for libraries, SDKs, frameworks
- Use for API-version-current reference instead of training-data-cache

### Playwright / Browser MCPs
- Browser automation for visual verification of market state, dashboard screenshots, manual execution when APIs fail

---

## Auth and secrets handling (universal rules)

1. **Never commit `.env`**. `.gitignore` it on day 1.
2. **Per-process secret isolation**. Tag each process with `PROCESS_ID_PREFIX=xxx` and ensure DB IDs don't collide.
3. **CRLF-safe env parsing**. Windows-edited `.env` on Linux VPS keeps `\r`; `source .env` in bash returns `%0D`-suffixed values. Defensively `.trim()` every env read.
4. **Validate at startup**. Fail fast with clear error messages if required env is missing or malformed. Don't let the bot boot with a broken key and crash 5 minutes later.
5. **Proxy wallet > EOA**. For venues with proxy-wallet architecture (Polymarket), the proxy address is what holds funds. The EOA signs on behalf of the proxy. Using EOA as the "address" silently breaks everything.

---

## Rate-limit management

- **Implement exponential backoff everywhere**. 429s should not crash the strategy — they should trigger a cooldown and retry.
- **Scanner-level rate budgeting**. If you have 10 scanners polling the same API, coordinate via a shared limiter rather than independent backoff.
- **Fallback data sources**. For critical paths (reference price, orderbook), have a secondary source that doesn't share rate-limit infrastructure with the primary.

---

## When APIs lie

These are DOCUMENTED behaviors in the field, not bugs per se, but deviations from what you'd expect from reading docs:

- Polymarket Gamma `_q=` free-text search returns GTA VI catch-all
- Kalshi orderbook endpoint returns `orderbook_fp`, not `orderbook`
- Kalshi `close_time` can be 2 years in the future for sports tickers
- CoinGecko demo key `429`s under any production-like load
- Public Polygon RPCs silently drop `contract.on()` events
- Polymarket proxy-wallet factory emits no creation events and returns the factory address when queried for owner

Always smoke-test against a real venue/market before trusting documented behavior.
