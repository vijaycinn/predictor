# Cross-venue live flip — PMXT vs Kalshi (2026-08-04)

VJ asked for "sports, especially the ATP tournament that is live, when looking
for live flip from pmxt vs kalshi". Session outcome: NO executable flip existed
because the Kalshi leg was dead — but the workflow to PROVE that (fast, without
burning 20 API calls) is the lesson. This is the recipe.

## The trap: PMXT events look live, Kalshi already resolved

`pmxt fetchEvents(series=KXATPCHALLENGERMATCH, exchange=kalshi)` returned:
- Monteiro vs Gentzsch — volume24h $576k
- Durasovic vs Geerts — volume24h $464k
- Molleker vs Mrva, Bar Biryukov vs Inchauspe, etc.

Native Kalshi check (`GET /markets/KXATPCHALLENGERMATCH-26AUG04MONGEN-MON`):
`status: finalized`, `close_time: 2026-08-04T12:30:59Z`, orderbook EMPTY.
PMXT volume24h was Polymarket-side volume from earlier trading, NOT Kalshi
liquidity. **PMXT event status ≠ Kalshi market status.** Always verify native.

## Verified recipes (all hit live 2026-08-04)

### 1. Enumerate Kalshi series events (native, works)
```python
GET /events?series_ticker=KXATPCHALLENGERMATCH&status=open&limit=200  # 36 events
GET /events?series_ticker=KXATPMATCH&status=open&limit=200            # 32 events
```
- Series tickers: `KXATPCHALLENGERMATCH` (challengers), `KXATPMATCH` (main
  tour). `KXATPMATCH-26AUG01SVASHA` = event-level ticker; market tickers are
  event ticker + player abbrev suffix (e.g. `-SVA`, `-SHA`).
- `/events` first page = long-dated junk (Mars, Pope, 2036 GDP). Filter by
  series_ticker, NOT title search on page 1.
- Numeric cursor pagination (`?cursor=N`) → 400. Use `cursor` token from
  response or series_ticker filter instead.
- `scripts/search_market.py` events cache can be STALE — returned 0 matches
  for live challengers. Don't trust it for same-day live markets; hit
  `/events?series_ticker=` directly.

### 2. Orderbook field trap (native Kalshi)
- Key is `orderbook_fp` (NOT `orderbook`): `{"yes_dollars": [[price,size]...],
  "no_dollars": [[price,size]...]}`.
- **prices AND sizes are STRINGS** — `float()` both. Comparing raw str vs int
  throws `TypeError: '>' not supported between instances of 'str' and 'int'`.
- NO-side math: `ap = 1 - float(asks[0][0])` where asks come from
  `no_dollars` (Kalshi no_dollars are NO prices, invert to YES).
- Placeholder book = `0.01/0.99` with volume 0 → market exists but NOT
  tradeable. Kalshi ATP pre-market and dead markets both show this.
- `GET /markets/{ticker}` for a FINALIZED market → 404. Use `/markets?event_ticker=`
  with status filter to see finalized ones.

### 3. Polymarket gamma (native, for the PMKT leg)
- 403 without headers: `User-Agent: Mozilla/5.0` + `Accept: application/json`.
- `GET /events?limit=100&active=true&closed=false&order=volume24hr&ascending=false`
  then client-side filter for tennis (tag param unreliable; `tags` field check
  for 'tennis'/'atp'/'wta').
- `outcomes` is a JSON **string**, not array — `json.loads()` it.
- Live price = `bestBid`/`bestAsk`; `outcomePrices` may be stale/terminal
  (0.999 = done). `lastTradePrice` also stale. For winner market dedupe by
  max `volume24hr` among 2-outcome markets.
- Verified 2026-08-04 live: Damm Jr vs Tsitsipas 36.5c, Svajda vs Shapovalov
  42.5c, Klok vs Teunissen 50.5c, Svitolina vs Bouzas Maneiro 76c.

### 4. 429 backoff — PMXT and Kalshi both throttle
- PMXT: 3+ back-to-back `fetchOrderBook` → 429 `Rate exceeded.` (plain text,
  SDK misreports as `Expecting value: line 1 column 1`), circuit breaker
  ~56s. `fetchOrderBooks` batch variant ALSO 429s under load. Sleep ≥8s
  between pmxt book calls, or go native Kalshi.
- Kalshi native: burst of per-market orderbook calls → 429. One paced script
  with `time.sleep(0.15-0.4)` per market works; 36 events × 3 calls does not.
- Router cross-venue methods (`fetchMarketMatches`, `fetchEventMatches`,
  `fetchArbitrage`) only work with `exchange="router"` — `kalshi`/`polymarket`
  return "Method not supported".

## The verdict pattern (mid-day US dead zone)

10:30 CT 2026-08-04: Kalshi ATP = all pre-market (0 vol) or finalized. Live
tennis volume sat on Polymarket. Cross-venue arb impossible — Polymarket leg
liquid, Kalshi leg empty placeholder book. Kalshi ATP liquidity windows:
- morning US (EST matches starting)
- evening (Europe/Asia day sessions)

Mid-day US = structural gap, NOT a scan miss. Live-flip cron (30m) correctly
said "No flip-zone live markets" — the flip-zone criteria (mid 0.35-0.65,
spread ≤3c, depth ≥200, vol ≥$2k) filter out dead books by depth, which is
exactly right.
