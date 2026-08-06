# BTC Monthly One-Touch Markets + Liquidation-Signal Mapping (2026-08-04)

## Series map (verified live)

- `KXBTCMINMON-BTC-26AUG31` — "How low will BTC get in August?" — one-touch DOWN.
  Strikes (Aug 2026): 42.5k, 45k, 47.5k, 50k, 52.5k, 55k, 57.5k, 60k.
- `KXBTCMAXMON-BTC-26AUG31` — "How high will BTC get in August?" — one-touch UP.
  Strikes: 65k, 67.5k, 70k, 72.5k, 75k, 77.5k, 80k, 82.5k.
- Strikes every $2,500, monthly expiry (event ends last day of month, 23:59 ET).
- Market ticker suffix = strike in cents: `...26AUG31-6000000` = $60,000.
- Event lookup: `GET /events?series_ticker=KXBTCMINMON|KXBTCMAXMON`.
- Resolution: trimmed-mean CF BRTI (top/bottom 20% trimmed per minute), any
  minute crossing the strike resolves YES; `can_close_early: true` — closes the
  instant the criterion is met, 30-min settlement timer. Missing BRTI data →
  strike resolves NO.

## THE liquidity trap (VJ correction 2026-08-04)

`GET /markets/{ticker}/orderbook` returned EMPTY `orderbook_fp` arrays for these
one-touch markets while the market object showed real quotes:
- `KXBTCMINMON-...6000000`: OI 40,528, bid 0.48 / ask 0.50
- `KXBTCMAXMON-...7000000`: OI 52,514, bid 0.25 / ask 0.26
- `KXBTCMAXMON-...6500000`: OI 63,626, bid 0.82 / ask 0.83

**Read `yes_bid_dollars`/`yes_ask_dollars`/`open_interest_fp` from the market
object — never declare a market dead from an empty orderbook.** Orderbook only
for level/wall depth analysis (density mode), and even then string-cast:
`float(price)`, `float(size)`.

## Liquidation-pool signal → market mapping

Signal (perps liquidation heatmap / funding watch): "Heavy long liquidation pool
sitting at $62K. Likely to get swept soon."

1. **Map pool → strike**: round DOWN to nearest ladder strike. $62K pool → the
   $60K MINMON strike is the closest Kalshi expression. There is NO $62K strike
   — one-touch ladders are $2.5k coarse.
2. **The gap IS the discount**: 62K pool ≠ 60K touch. Market prices 60K MINMON
   at 48/50c because the sweep could stop at 62K. That 2k gap is why it's not
   60c. Don't treat signal level as strike level.
3. **Independent prob**: Polymarket gamma "Will Bitcoin dip to $60,000 in
   August?" = 45/46c at time of check. Kalshi 60K MINMON 0.49/0.50 = 4c RICH
   vs PM. Per rule 9 (ARB = SELL-ONLY on Kalshi): SELL YES at 0.50 (buy NO),
   edge = 0.50 − 0.46 = +4c. NOT a buy — buying Kalshi 0.45 "cheap" is a
   directional bet, not arb. If Kalshi is not rich on a side → SKIP.
4. **Existing positions ride the same thesis**: VJ held MINMON down-ladder
   (57.5k @ 35c, 55k @ 19c, 52.5k @ 12c). A 62K sweep doesn't fill them — they
   need the cascade deeper. Don't add on a weaker strike; hold.
5. **Cascade thesis only**: if the sweep is expected to run THROUGH 60k, then
   the 60K MINMON (or deeper strikes) becomes live. That's betting beyond the
   signal — requires its own evidence, not the pool level alone.

## Daily range markets — NOT one-touch (VJ ask 2026-08-06)

`KXBTC-<date>-B62250`-style markets ("Bitcoin price range on Aug 6 at 11am EDT",
buckets like $62,200–62,299.99) are SAME-DAY snapshot markets, NOT one-touch:
close at the snapshot time (15:00Z), zero volume/OI, dead book (bid 0.00/ask
0.01). If a search surfaces a "62K" BTC ticker, check `close_time` + OI first —
it's almost always this dead daily-range class. The only real expression of a
$62K-pool sweep is the 60K MINMON strike (round down the $2.5K ladder).

## Placement recipe — VJ-explicit one-touch buy (verified 2026-08-04)

VJ: "2 x for 60k at 0.45c for BTC minmon" — 2 contracts, `$60K` MINMON one-touch
at 0.45 (PM-implied fair, wall level). Direct placement, bypass LiveExecutor:

```python
sig = {'condition_id': 'KXBTCMINMON-BTC-26AUG31-6000000', 'side': 'YES',
       'approved_price': 0.45, 'ev_calc': {'price_side': 0.45},
       'override_price_band': True, 'override_win_floor': True}  # VJ-explicit
risk.pre_flight_check(sig, 0.45, cfg)          # still run the gate (asserts pass)
resp = kalshi.place_order(ticker, 'YES', 2.0, 0.45,
                          hours_to_expiry=0, max_lifetime_hours=720.0)
# TTL: monthly one-touch rides to resolution — NOT the 1h default, NOT 0.8×decay
```

- `override_*` flags required: 0.45 > 40c band and PM indep prob < 50% floor —
  VJ-explicit pick bypasses both (per predict skill VJ-explicit exception).
- TTL 720h = ride to month-end resolution, matches no-stop-loss rule.
- `place_order` returns `order_id` but NULLs for status/fields — verify via
  `get_order(order_id)`: resting fields `initial_count_fp` (2.00),
  `no_price_dollars` (0.55 → YES limit = 1−0.55 = 0.45), `status: resting`.
- Log locally: `db.insert_trade(...)` with `status: RESTING`,
  `exchange_order_id`, `ttl_expires_at = now + 30d`. Trade #42 in this case.
- Risk = 2 × 0.45 = $0.90 total, not per-contract (binary-risk comm rule).

## Polymarket gamma cross-venue (for the independent-prob leg)

- `GET /events?limit=100&active=true&closed=false&order=volume24hr&ascending=false`
  needs `User-Agent: Mozilla/5.0` + `Accept: application/json` (403 without).
- `outcomes` is a JSON **string** — `json.loads()` it.
- Live price = `bestBid`/`bestAsk`. `outcomePrices` can be terminal (["1","0"])
  for resolved markets — filter on bestBid not null.
- BTC events: "Bitcoin above ___ on <date>?" (strike ladders, "dip to $X" for
  one-touch down) and "What price will Bitcoin hit in <month>?" ("reach $X" =
  MAX analog, "dip to $X" = MIN analog). Cross-check the SAME strike, e.g. Kalshi
  60K MINMON vs Polymarket "dip to $60,000 in August".
- Spot sanity: CoinGecko `simple/price?ids=bitcoin&vs_currencies=usd` works;
  Binance = HTTP 451 (geo), Coinbase spot flaky. BTC ~$64,109 at session time.

## Kalshi API notes hit live

- `/events?limit=200` page 1 = long-dated junk (Mars, Pope, 2036 GDP) — always
  filter by `series_ticker` or paginate properly; numeric `?cursor=N` → 400.
- `/events/{id}` with a PMXT UUID → 404 (PMXT ids ≠ Kalshi ids). Resolve via
  native series enumeration or `/markets?event_ticker=`; PMXT `fetchMarket(slug=...)`
  works for Kalshi but `/events/{pmxt_uuid}` does NOT.
- Kalshi native bursts of per-market orderbook calls → 429; pace with
  `time.sleep(0.15-0.4)` per market or read market-object quotes instead.
- 401 on raw `urllib` GET `/portfolio/orders/{id}` — needs signed auth, use the
  repo's `kalshi.get_order()` wrapper, not raw requests with just KALSHI-API-KEY.
