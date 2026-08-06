# HyperTracker (CoinMarketMan) — crypto perps research (2026-08-06)

Hyperliquid perps on-chain analytics. Dashboard:
`https://app.coinmarketman.com/hypertracker/perps`. API docs:
`https://docs.coinmarketman.com/endpoints/...` (position-heatmap.md,
liquidation-data.md, llms.txt index).

## Why it exists in the stack

VJ's crypto research tool for market pricing + direction (2026-08-06). Feeds
the BTC one-touch thesis: verify "liquidation pool at $62K" claims with real
on-chain Hyperliquid data, map clusters to Kalshi strikes.

## Free tier (no key)

Perps dashboard = SvelteKit/React SPA, client-rendered. Raw `curl` returns a
JS shell (~15KB, no data). Two working reads:
1. `web_extract` on the perps URL (headless renderer) → full per-asset table:
   last, 24h vol, OI, funding, whale OI %, 24h whale bias.
2. Manual browser (if CDP backend up).

Columns observed live 2026-08-06: BTC 64,780 (whale OI 68%, slightly bullish),
ETH 1,915 (whale 82%, slightly bearish), GOLD 4,254, CL 76.9, BRENT 81.6.

## API tier (needs key)

`HYPERTRACKER_API_KEY` → `/data/.hermes/.env`. Free: 100 req/day, no card.
Paid: Pulse $179/mo 50k req, Surge $399, Flow $799, Stream $1,999.

Base: `https://ht-api.coinmarketman.com/api/external`
Auth: `Authorization: Bearer <key>`

Endpoints (verified from docs 2026-08-06):
- `GET /positions/heatmap?openedWithin=24h` — per coin, per trader segment:
  `totalLongValue`, `totalShortValue`, `count`, `bias` (0-1, >0.5 = long lean).
  Segment ~= trader cohort (size/PnL tiers).
- `GET /exports/coins/{COIN}/liquidation-heatmap` — price bins
  (`priceBinStart/End`), `liquidationValue`, `positionsCount`,
  `mostImpactedSegment`. THE liquidation-pool data. 200 response includes
  `heatmap` array (despite doc showing a pre-signed URL pattern, the JSON
  comes back inline).
- `GET /fills/liquidation?coin=BTC&limit=N` — recent liq fills: `px`, `sz`,
  `side` (A=ask/sell, B=bid/buy), `closedPnl`, `liquidationMarkPx`,
  `dir` ("Close Short"/"Close Long").

## Strike mapping

Kalshi one-touch ladders are $2.5K coarse (MIN 42.5k-60k, MAX 65k-82.5k Aug).
`strike_map(price)` in scripts/hypertracker.py: round DOWN to nearest $2.5K;
price >= 65000 → KXBTCMAXMON, else KXBTCMINMON. 62K pool → 60K MINMON.
Pool level ≠ strike level — the gap is why the strike trades 49c not 60c.

## Script usage

```bash
# free dashboard scrape (coins filter)
python3 scripts/hypertracker.py "BTC,ETH,GOLD,SOL"
# API tier (key in env)
python3 scripts/hypertracker.py "BTC,ETH" --api
```

## Pitfalls

- 100 req/day free — batch, never poll. 429 = quota/limit, back off.
- Dashboard markup is minified SPA; regex-scrape is fragile. Prefer
  web_extract in-session, or API when key present.
- Liquidation heatmap bins can be coarse at extremes; cross-check spot.
- Docs mention pre-signed download URLs for exports; observed response shape
  includes the heatmap array directly — handle both defensively.
