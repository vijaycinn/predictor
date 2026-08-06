# PMXT Router arb + Predexon matching (verified 2026-08)

## PMXT (primary arb discovery)

- `pmxt` Python SDK, `PMXT_API_KEY` env. Router methods (snake_case):
  - `fetch_arbitrage()` → identity-relation pairs `{market_a, market_b, spread, buy_venue, sell_venue, buy_price, sell_price}`, confidence 1
  - `fetch_matched_market_clusters(market_obj, ...)` — takes market OBJECT, not `marketId` kwarg (SDK error trap)
  - `fetch_markets(query=)` is FLAKY (returns 0) — anchor clusters from arbitrage objects instead
- Kalshi market `slug` IS the native ticker; Polymarket market_id is PMXT UUID
- PMXT = discovery, not truth. Validate Kalshi legs against Predexon live prices (search by TITLE — Predexon matches titles, not tickers; then exact-ticker check)
- Flakes intermittently (empty JSON) — wrap with Predexon fallback (`arb.arb_check`)

## Predexon

- NO `find_matching_markets` tool (verified: npm source predexon-mcp@0.3.0, REST openapi 62 paths, docs). Build matching locally.
- Kalshi = data only (no trading via Predexon)
- Matching: per-market Polymarket SEARCH (never random top-N pool), Jaccard token-SET similarity (≥0.85 strong), disqualifier-token asymmetry rejects (vice/senate/house/governor/primary/runoff...), Kalshi yes/no_subtitle appended, close-time + numeric-target gates. Weak matches never surface.

## Arb math

- Synthetic arb: buy YES@A + NO@B across venues; combined < $1.00 → gross edge = 1 - combined
- Minus fees (Polymarket bps × p × (1-p); Kalshi 0) minus ~1 tick slippage
- Gate: net edge ≥ 2c. Limit orders only. Abort if either leg can't fill.
- CLI: `cli.py arb --pmxt` (PMXT feed) | `cli.py arb --check` (Predexon matcher)
