# Kalshi v2 API (reverse-engineered, verified live 2026-08)

Base: `https://external-api.kalshi.com/trade-api/v2`

## Auth (RSA-PSS)

- Headers: `KALSHI-ACCESS-KEY` (key ID UUID), `KALSHI-SIGNATURE` (base64 RSA-PSS/SHA256), `KALSHI-TIMESTAMP` (ms epoch)
- Sign: `{timestamp}{METHOD}{FULL path}` — MUST include `/trade-api/v2` prefix. Short-path sigs fail strict endpoints with `INCORRECT_API_KEY_SIGNATURE` (balance endpoint is lenient — deceptive trap).
- Keys from env at call time: `KALSHI_API_KEY` + `KALSHI_PRIVATE_KEY` (RSA PEM).
- 401/429 transient — retry 5x with backoff 1.5s base.

## Orders (V2)

- POST `/portfolio/orders` body: `{ticker, side: bid|ask, count, price, time_in_force}` — all strings, price in dollars (0.74 = 74¢)
- side: `bid` = buy YES, `ask` = buy NO (sell YES). NO price = own NO price (1 - YES)
- GET `/portfolio/orders?status=resting` — list; `{order_id}` — detail
- DELETE `/portfolio/orders/{order_id}` — cancel
- GET `/portfolio/positions`, `/portfolio/fills`, `/portfolio/balance`

## Market data

- Orderbook: bids only (yes_dollars, no_dollars arrays; NO ask = 1 - best YES bid)
- `/events` caps limit 200/page; `/markets` list lacks category/series → build event→category map, cache 1h
- `mve_filter=exclude` kills MVE combo junk
- Volumes ~10x smaller than Polymarket — per-venue scan gates
- Candlesticks: `/series/{series}/markets/{ticker}/candlesticks` needs `start_ts`

## Gotchas

- Market by id via `/markets/{ticker}` — Kalshi uses tickers (KX...) not UUIDs
- Wallet is internal (no external wallet/gas) — live trading practical
